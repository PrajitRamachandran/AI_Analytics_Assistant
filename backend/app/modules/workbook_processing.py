"""Orchestrate the Module 2 workbook processing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from app.modules.data_cleaning import CleaningConfig, CleaningResult, clean_workbook
from app.modules.data_normalization import NormalizationResult, normalize_workbook
from app.modules.excel_ingestion import (
    WorkbookIngestionResult,
    ingest_excel_workbook,
)


@dataclass
class WorkbookProcessingResult:
    """Holds the output of each processing stage for downstream modules."""

    ingestion: WorkbookIngestionResult
    normalization: NormalizationResult
    cleaning: CleaningResult


def process_workbook(
    file_path: Union[str, Path],
    cleaning_config: Optional[CleaningConfig] = None,
) -> WorkbookProcessingResult:
    """Run ingestion, normalization, and cleaning in sequence.

    The original workbook is never modified. Each stage creates or returns
    in-memory DataFrames; no global state or database persistence is used.
    Worksheet-level errors are carried forward by the individual stages.

    Args:
        file_path: Path to the ``.xlsx``/``.xlsm`` workbook.
        cleaning_config: Optional cleaning switches; defaults are conservative.
    """
    ingestion_result = ingest_excel_workbook(file_path)
    normalization_result = normalize_workbook(ingestion_result)
    cleaning_result = clean_workbook(normalization_result, cleaning_config)

    return WorkbookProcessingResult(
        ingestion=ingestion_result,
        normalization=normalization_result,
        cleaning=cleaning_result,
    )
