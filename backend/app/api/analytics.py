"""End-to-end Module 4 planning and deterministic analytics execution API."""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.core.database import get_db_connection
from app.core.dataset_state import ensure_state_schema, save_dataset_stage, get_selected_model, load_processing_artifact
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
from app.schemas.data_understanding import DatasetProfile

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
def generate_dataset_analytics(dataset_id: str, force: bool = Query(False, description='Regenerate analytics.')) -> dict:
    """Run Modules 2–5 in one request and return deterministic chart data."""
    try:
        ensure_state_schema()
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT filename, storage_path, status, analytics_result, understanding_result
                    FROM datasets
                    WHERE dataset_id = %s;
                    """,
                    (dataset_id,),
                )
                dataset = cursor.fetchone()

        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found.")

        
        filename, storage_path, status, cached_analytics, cached_profile = dataset
        if cached_analytics and not force:
            return {**cached_analytics, "cached": True, "message": "Previously generated analytics restored from PostgreSQL."}
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
            processing_result = load_processing_artifact(dataset_id) or process_workbook(workbook_path)
            profile = (DatasetProfile.model_validate(cached_profile) if cached_profile else profile_dataset(processing_result.cleaning))
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
        if not cached_profile:
            save_dataset_stage(dataset_id, "understanding_result", profile, "understood_at")
        selected_model = get_selected_model()
        from app.modules.analytics_planner.llm_client import create_llm_client
        plan_generator = create_llm_client(
            provider=selected_model.get("provider") or None,
            model=selected_model.get("model") or None,
        )
        plan = AnalyticsPlanner(plan_generator=plan_generator).generate_plan(profile)

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
        output["cached"] = False
        try:
            save_dataset_stage(dataset_id, "analytics_result", output, "analysed_at")
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Analytics generated, but results could not be persisted.") from exc
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
