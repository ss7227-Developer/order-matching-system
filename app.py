from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from engine import MatchingEngine
from order import CancelledOrder, OrderRequest, SubmitResult

app = FastAPI()
engine = MatchingEngine()


@app.post("/orders", response_model=SubmitResult, status_code=201)
def submit_order(request: OrderRequest) -> SubmitResult:
    return engine.submit_order(request)


@app.delete("/orders/{order_id}", response_model=CancelledOrder)
def cancel_order(order_id: str, owner_id: int) -> CancelledOrder:
    result = engine.cancel_order(order_id, owner_id)
    if result is None:
        raise HTTPException(status_code=404, detail="order not found")
    return result


@app.get("/orderbook")
def orderbook() -> dict:
    return engine.snapshot()
