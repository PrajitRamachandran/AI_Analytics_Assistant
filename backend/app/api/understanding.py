"""API endpoint for generating Module 3 dataset profiles."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.core.database import get_db_connection
from app.core.dataset_state import ensure_state_schema, save_dataset_stage, load_processing_artifact
from app.modules.data_understanding import profile_dataset
from app.modules.excel_ingestion import ExcelIngestionError
from app.modules.workbook_processing import process_workbook
from app.schemas.data_understanding import DatasetProfile

router = APIRouter(prefix="/api", tags=["Data Understanding"])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"


def _get_safe_storage_path(storage_path: str) -> Path:
    """Resolve a stored workbook path and prevent access outside uploads."""
    base_dir = UPLOAD_DIR.resolve()
    file_path = Path(storage_path).resolve()

    if base_dir not in file_path.parents or file_path.name != "workbook.xlsx":
        raise HTTPException(
            status_code=500,
            detail="Invalid dataset storage location.",
        )

    return file_path


@router.post(
    "/datasets/{dataset_id}/understand",
    response_model=DatasetProfile,
    summary="Generate a structured profile for an already processed dataset",
)
def understand_dataset(dataset_id: str, force: bool = Query(False, description='Regenerate the dataset profile.')) -> DatasetProfile:
    """Re-run Module 2 and profile its cleaned DataFrames using Module 3.

    The uploaded workbook remains unchanged. DataFrames are created in memory
    for this request and are not persisted. The dataset must first complete
    the Module 2 processing action.
    """
    try:
        # Retrieve only the metadata required for this operation.
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT filename, storage_path, status, understanding_result
                    FROM datasets
                    WHERE dataset_id = %s;
                    """,
                    (dataset_id,),
                )
                dataset = cursor.fetchone()

        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found.")

        ensure_state_schema()
        filename, storage_path, dataset_status, cached_profile = dataset
        if cached_profile and not force:
            return cached_profile

        if dataset_status != "processed":
            raise HTTPException(
                status_code=409,
                detail="Dataset must be processed successfully before it can be understood.",
            )

        file_path = _get_safe_storage_path(storage_path)
        if not file_path.is_file():
            raise HTTPException(
                status_code=404,
                detail="The stored Excel file could not be found.",
            )

        try:
            # Module 2 is deliberately reused as the single source of truth
            # for ingestion, normalisation and cleaning.
            processing_result = load_processing_artifact(dataset_id) or process_workbook(file_path)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="The stored Excel workbook could not be found.",
            ) from exc
        except (ExcelIngestionError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Unable to process workbook for profiling: {exc}",
            ) from exc

        profile = profile_dataset(processing_result.cleaning)

        if profile.successful_worksheet_count == 0:
            error_summary = "; ".join(
                f"{sheet}: {message}"
                for sheet, message in profile.worksheet_errors.items()
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    "No worksheets could be profiled. "
                    f"{error_summary}" if error_summary else
                    "No worksheets could be profiled."
                ),
            )

        # Module 2 sees the stored filename (workbook.xlsx); expose the
        # original user-facing filename in the API response instead.
        profile = profile.model_copy(update={"filename": filename})
        try:
            save_dataset_stage(dataset_id, "understanding_result", profile, "understood_at")
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Profile generated, but could not be saved.") from exc
        return profile

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to generate the dataset profile.",
        ) from exc
