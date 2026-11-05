
from pathlib import Path
import shutil

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.database import get_db_connection

router = APIRouter(prefix="/api", tags=["Datasets"])

# Same upload directory used by upload.py
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"


def get_safe_storage_path(storage_path: str) -> Path:
    """Ensure the requested file belongs to our upload directory."""

    base_dir = UPLOAD_DIR.resolve()
    file_path = Path(storage_path).resolve()

    if (
        base_dir not in file_path.parents
        or file_path.name != "workbook.xlsx"
    ):
        raise HTTPException(
            status_code=500,
            detail="Invalid dataset storage location."
        )

    return file_path


# GET: Retrieve all uploaded datasets
@router.get("/datasets")
async def get_datasets():

    try:
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        dataset_id,
                        filename,
                        file_size,
                        status,
                        uploaded_at
                    FROM datasets
                    ORDER BY uploaded_at DESC;
                    """
                )

                rows = cursor.fetchall()

        datasets = []

        for row in rows:
            datasets.append({
                "dataset_id": str(row[0]),
                "filename": row[1],
                "file_size": row[2],
                "status": row[3],
                "uploaded_at": (
                    row[4].isoformat() if row[4] else None
                )
            })

        return {
            "status": "success",
            "total": len(datasets),
            "datasets": datasets
        }

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve uploaded datasets."
        )


# GET: Download an uploaded Excel workbook
@router.get("/datasets/{dataset_id}/download")
async def download_dataset(dataset_id: str):

    try:
        with get_db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT filename, storage_path
                    FROM datasets
                    WHERE dataset_id = %s;
                    """,
                    (dataset_id,)
                )

                dataset = cursor.fetchone()

        if not dataset:
            raise HTTPException(
                status_code=404,
                detail="Dataset not found."
            )

        filename, storage_path = dataset
        file_path = get_safe_storage_path(storage_path)

        if not file_path.is_file():
            raise HTTPException(
                status_code=404,
                detail="The stored Excel file could not be found."
            )

        return FileResponse(
            path=file_path,
            filename=filename,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            )
        )

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Unable to download the requested dataset."
        )


# DELETE: Remove an uploaded workbook and its database record
@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str):

    try:
        with get_db_connection() as connection:
            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT storage_path
                    FROM datasets
                    WHERE dataset_id = %s
                    FOR UPDATE;
                    """,
                    (dataset_id,)
                )

                dataset = cursor.fetchone()

                if not dataset:
                    raise HTTPException(
                        status_code=404,
                        detail="Dataset not found."
                    )

                file_path = get_safe_storage_path(dataset[0])
                dataset_dir = file_path.parent

                # Delete the stored workbook and its folder
                if dataset_dir.exists():
                    shutil.rmtree(dataset_dir)

                cursor.execute(
                    """
                    DELETE FROM datasets
                    WHERE dataset_id = %s;
                    """,
                    (dataset_id,)
                )

        return {
            "status": "success",
            "message": "Dataset deleted successfully.",
            "dataset_id": dataset_id
        }

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Unable to delete the requested dataset."
        )