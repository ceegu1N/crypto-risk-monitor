from collections.abc import Generator

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session


def get_session(request: Request) -> Generator[Session, None, None]:
    with request.app.state.session_factory() as session:
        yield session


def require_operator(request: Request) -> None:
    if request.session.get("operator") is not True:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="operator authentication required",
        )
