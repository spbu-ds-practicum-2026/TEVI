from fastapi import FastAPI, Request, Response

app = FastAPI()


@app.post("/handle")
async def handle(request: Request) -> Response:
    await request.body()
    return Response(status_code=200)