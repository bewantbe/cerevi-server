"""Unified /metadata and /data endpoints.

Endpoints:
  GET /metadata?type=specimens
  GET /metadata?type=regions&specimen={specimen_id}
  GET /data/{data_id}

See README.md for details.
"""

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse, Response
import logging
from typing import Literal

from ..services.data_service import DataService

router = APIRouter()
logger = logging.getLogger(__name__)

data_service = DataService()


@router.get('/metadata')
async def fetch_metadata(
        type: Literal["specimens", "regions"] = Query(..., description="Metadata type: specimens | regions"),
        specimen: str | None = Query(None, description="Specimen ID for regions")):
    try:
        if type == 'specimens':
            specimens = data_service.load_specimens_metadata()
            return JSONResponse(content=specimens)
        if type == 'regions':
            if not specimen:
                raise HTTPException(status_code=400, detail="specimen query param required for regions metadata")
            regions = data_service.get_regions_metadata(specimen)
            return JSONResponse(content=regions)
        raise HTTPException(status_code=400, detail="Unsupported metadata type")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to serve metadata")
        raise HTTPException(status_code=500, detail="Internal error serving metadata")


@router.get('/data/{data_id}')
async def fetch_data_piece(data_id: str):
    try:
        parsed = data_service.parse_data_id(data_id)
        if parsed.modality in ('img', 'msk'):
            bytes_out = data_service.get_tile_bytes(parsed)
            # return raw bytes and let the receiver interpret the format (e.g. uint16 raw)
            # use a generic binary content type instead of forcing jpeg/png
            return Response(content=bytes_out, media_type='application/octet-stream')
        if parsed.modality == 'meh':
            mesh_bytes = data_service.get_mesh_bytes(parsed)
            return Response(content=mesh_bytes, media_type='text/plain')
        raise HTTPException(status_code=400, detail='Unsupported modality')
    except (ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Failed to serve data")
        raise HTTPException(status_code=500, detail='Internal error serving data')
