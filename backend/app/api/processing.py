"""API endpoint for processing previously uploaded Excel datasets."""

from datetime import date, datetime
from pathlib import Path
from typing import Any
import math

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from app.core.database import get_db_connection
from app.core.dataset_state import ensure_state_schema, save_dataset_stage, save_processing_artifact
from app.modules.excel_ingestion import ExcelIngestionError
from app.modules.workbook_processing import process_workbook

router = APIRouter(prefix="/api", tags=["Processing"])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
PREVIEW_ROW_LIMIT = 10


def _get_safe_storage_path(storage_path: str) -> Path:
    """Ensure a database path resolves to a workbook inside uploads."""
    base_dir = UPLOAD_DIR.resolve()
    file_path = Path(storage_path).resolve()

    if (
        base_dir not in file_path.parents
        or file_path.name != "workbook.xlsx"
    ):
        raise HTTPException(
            status_code=500,
            detail="Invalid dataset storage location.",
        )

    return file_path


def _json_safe_value(value: Any) -> Any:
    """Convert Pandas/NumPy/date values into JSON-compatible Python values."""
    if value is None:
        return None

    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()

    if isinstance(value, np.generic):
        value = value.item()

    try:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and missing:
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, float) and not math.isfinite(value):
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


def _build_worksheet_response(processing_result, worksheet_name: str) -> dict:
    """Create a compact worksheet summary and preview for the frontend."""
    dataframe = processing_result.cleaning.worksheets[worksheet_name]
    quality_report = processing_result.cleaning.quality_reports[worksheet_name]

    mappings = {
        item.normalized_name: item.original_name
        for item in processing_result.cleaning.column_mappings.get(
            worksheet_name, []
        )
    }
    types = {
        item.normalized_name: item
        for item in processing_result.cleaning.column_types.get(
            worksheet_name, []
        )
    }
    quality = {
        item.column_name: item
        for item in quality_report.column_quality
    }
    normalization_audits = {
        item.normalized_name: item
        for item in processing_result.normalization.value_normalizations.get(
            worksheet_name, []
        )
    }

    columns = []
    for column_name in dataframe.columns:
        name = str(column_name)
        type_info = types.get(name)
        quality_info = quality.get(name)

        normalization_info = normalization_audits.get(name)
        columns.append({
            "name": name,
            "original_name": str(mappings.get(name, name)),
            "pandas_dtype": (
                type_info.pandas_dtype if type_info else str(dataframe[name].dtype)
            ),
            "data_category": (
                type_info.data_category if type_info else "other"
            ),
            "missing_value_count": (
                quality_info.missing_value_count if quality_info else 0
            ),
            "blank_string_count": (
                quality_info.blank_string_count if quality_info else 0
            ),
            "missing_percentage": (
                quality_info.missing_percentage if quality_info else 0.0
            ),
            "whitespace_padded_string_count": (
                quality_info.whitespace_padded_string_count if quality_info else 0
            ),
            "mixed_value_types": (
                quality_info.mixed_value_types if quality_info else []
            ),
            "normalization": {
                "semantic_type": normalization_info.semantic_type,
                "target_format": normalization_info.target_format,
                "cells_changed": normalization_info.cells_changed,
                "unparseable_count": normalization_info.unparseable_count,
                "unparseable_samples": normalization_info.unparseable_samples,
                "notes": normalization_info.notes,
            } if normalization_info else None,
        })

    preview = []
    for _, row in dataframe.head(PREVIEW_ROW_LIMIT).iterrows():
        preview.append({
            str(column_name): _json_safe_value(row[column_name])
            for column_name in dataframe.columns
        })

    return {
        "worksheet_name": worksheet_name,
        "row_count": int(len(dataframe)),
        "column_count": int(len(dataframe.columns)),
        "columns": columns,
        "preview": preview,
        "quality": {
            "original_row_count": quality_report.original_row_count,
            "original_column_count": quality_report.original_column_count,
            "cleaned_row_count": quality_report.cleaned_row_count,
            "cleaned_column_count": quality_report.cleaned_column_count,
            "empty_row_positions": quality_report.empty_row_positions,
            "empty_column_names": quality_report.empty_column_names,
            "duplicate_row_count": quality_report.duplicate_row_count,
            "removed_empty_row_count": quality_report.removed_empty_row_count,
            "removed_empty_column_count": quality_report.removed_empty_column_count,
            "removed_duplicate_row_count": quality_report.removed_duplicate_row_count,
            "total_missing_value_count": sum(
                item.missing_value_count for item in quality_report.column_quality
            ),
            "total_blank_string_count": sum(
                item.blank_string_count for item in quality_report.column_quality
            ),
            "total_whitespace_padded_string_count": sum(
                item.whitespace_padded_string_count
                for item in quality_report.column_quality
            ),
        },
    }


@router.post("/datasets/{dataset_id}/process")
def process_dataset(dataset_id: str, force: bool = Query(False, description="Re-run processing even when a cached result exists.")):
    """Run the Module 2 pipeline for an uploaded dataset and return its summary."""
    try:
        ensure_state_schema()
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT filename, storage_path, processing_result
                    FROM datasets
                    WHERE dataset_id = %s;
                    """,
                    (dataset_id,),
                )
                dataset = cursor.fetchone()

        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found.")

        
        filename, storage_path, cached_result = dataset
        if cached_result and not force:
            return {**cached_result, "cached": True, "message": "Dataset already processed; returning saved processing output."}
        file_path = _get_safe_storage_path(storage_path)

        if not file_path.is_file():
            raise HTTPException(
                status_code=404,
                detail="The stored Excel file could not be found.",
            )

        try:
            processing_result = process_workbook(file_path)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail="The stored Excel workbook could not be found.",
            )
        except (ExcelIngestionError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Unable to process workbook: {exc}",
            ) from exc

        worksheet_results = {
            worksheet_name: _build_worksheet_response(
                processing_result, worksheet_name
            )
            for worksheet_name in processing_result.cleaning.worksheets
        }

        errors = processing_result.cleaning.worksheet_errors
        successful_count = processing_result.cleaning.successful_worksheet_count
        failed_count = processing_result.cleaning.failed_worksheet_count

        if successful_count == 0:
            error_summary = "; ".join(
                f"{sheet}: {message}" for sheet, message in errors.items()
            )
            raise HTTPException(
                status_code=422,
                detail=f"No worksheets could be processed. {error_summary}",
            )

        response = {
            "status": "success",
            "message": "Workbook processed successfully."
            if failed_count == 0
            else "Workbook processed with worksheet errors.",
            "dataset_id": dataset_id,
            "filename": filename,
            "processing": {
                "total_worksheet_count": processing_result.ingestion.total_worksheet_count,
                "successful_worksheet_count": successful_count,
                "failed_worksheet_count": failed_count,
                "preview_row_limit": PREVIEW_ROW_LIMIT,
                "normalized_cell_count": sum(
                    audit.cells_changed
                    for audits in processing_result.normalization.value_normalizations.values()
                    for audit in audits
                ),
                "unparseable_cell_count": sum(
                    audit.unparseable_count
                    for audits in processing_result.normalization.value_normalizations.values()
                    for audit in audits
                ),
            },
            "worksheets": worksheet_results,
            "worksheet_errors": errors,
            "cached": False,
        }

        try:
            save_dataset_stage(dataset_id, 'processing_result', response, 'processed_at')
            save_processing_artifact(dataset_id, processing_result)
            with get_db_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute('UPDATE datasets SET status = %s WHERE dataset_id = %s', ('processed', dataset_id))
        except Exception as exc:
            raise HTTPException(status_code=500, detail='Workbook processed, but its result could not be persisted.') from exc
        return response

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to process the requested dataset.",
        ) from exc
