"""End-to-end Module 4 planning and deterministic analytics execution API."""
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.database import get_db_connection
from app.modules.analytics_execution import (
    AnalyticsExecutionError,
    execute_analytics_plan,
)
from app.modules.analytics_planner.analytics_planner import (
    AnalyticsPlanner,
    AnalyticsPlannerError,
    AnalyticsPlanningTimeoutError,
    AnalyticsProviderUnavailableError,
)
from app.modules.analytics_planner.plan_validator import AnalyticalPlanValidationError
from app.modules.analytics_planner.profile_preparation import ProfilePreparationError
from app.modules.analytics_planner.prompt_builder import PromptBuilderError
from app.modules.analytics_planner.worksheet_classifier import classify_worksheet
from app.modules.data_understanding import profile_dataset
from app.modules.excel_ingestion import ExcelIngestionError
from app.modules.workbook_processing import process_workbook

router = APIRouter(prefix="/api", tags=["Analytics"])
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"


def _safe_workbook_path(storage_path: str) -> Path:
    base_dir = UPLOAD_DIR.resolve()
    path = Path(storage_path).resolve()
    if base_dir not in path.parents or path.name != "workbook.xlsx":
        raise HTTPException(status_code=500, detail="Invalid dataset storage location.")
    return path


@router.post(
    "/datasets/{dataset_id}/analytics",
    summary="Generate a validated analytics plan and execute it",
)
def generate_dataset_analytics(dataset_id: str) -> dict:
    """Run Modules 2–5 in one request and return deterministic chart data."""
    try:
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT filename, storage_path, status
                    FROM datasets
                    WHERE dataset_id = %s;
                    """,
                    (dataset_id,),
                )
                dataset = cursor.fetchone()

        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found.")

        filename, storage_path, status = dataset
        if status != "processed":
            raise HTTPException(
                status_code=409,
                detail="Process the workbook successfully before generating analytics.",
            )

        workbook_path = _safe_workbook_path(storage_path)
        if not workbook_path.is_file():
            raise HTTPException(
                status_code=404,
                detail="The stored Excel workbook could not be found.",
            )

        try:
            processing_result = process_workbook(workbook_path)
            profile = profile_dataset(processing_result.cleaning)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Workbook not found.") from exc
        except (ExcelIngestionError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Unable to prepare workbook for analytics: {exc}",
            ) from exc

        if profile.successful_worksheet_count == 0:
            raise HTTPException(
                status_code=422,
                detail="No worksheets could be profiled for analytics.",
            )

        profile = profile.model_copy(update={"filename": filename})
        plan = AnalyticsPlanner().generate_plan(profile)

        # Keep reference/documentation sheets in the workbook plan and
        # worksheet count, but exclude them from business row totals and
        # deterministic analytical execution.
        analytical_worksheets = {
            worksheet_name: dataframe
            for worksheet_name, dataframe in processing_result.cleaning.worksheets.items()
            if worksheet_name in profile.worksheets
            and classify_worksheet(
                worksheet_name,
                profile.worksheets[worksheet_name],
            )["role"] == "analytical"
        }

        try:
            output = execute_analytics_plan(
                analytical_worksheets,
                plan,
            )
        except AnalyticsExecutionError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"The validated plan could not be executed: {exc}",
            ) from exc

        output["filename"] = filename
        output["dataset_id"] = dataset_id
        output["execution_status"] = "success"
        return output

    except HTTPException:
        raise
    except AnalyticalPlanValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"The generated analytics plan did not pass dataset validation: {exc}",
        ) from exc
    except AnalyticsPlanningTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Analytics planning timed out: {exc}",
            headers={"Retry-After": "30"},
        ) from exc
    except AnalyticsProviderUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Analytics provider unavailable: {exc}",
        ) from exc
    except (AnalyticsPlannerError, ProfilePreparationError, PromptBuilderError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Analytics planning failed: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to generate analytics for this workbook.",
        ) from exc
