"""Request dependencies: DB session and faculty authorization (RULES R-85, ADR-016)."""
import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from .errors import ApiError


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as s:
        yield s


def require_faculty(request: Request,
                    x_faculty_key: Annotated[str | None, Header(alias="X-Faculty-Key")] = None) -> None:
    """Fail closed: no configured key → every write is disabled. Constant-time comparison.
    ponytail: no per-IP lockout; a >=16-char random key makes guessing impractical. Add rate
    limiting at the proxy if the key ever has to be short or shared widely."""
    st = request.app.state.settings
    if not st.writes_enabled:
        raise ApiError(503, "writes_disabled",
                       "Faculty changes are disabled: no faculty access key is configured on the server.")
    if not x_faculty_key:
        raise ApiError(401, "auth_required", "Enter the faculty key to make changes.",
                       headers={"WWW-Authenticate": 'FacultyKey realm="acadza"'})
    expected = st.faculty_access_key.get_secret_value().encode("utf-8")
    if not hmac.compare_digest(x_faculty_key.encode("utf-8"), expected):
        raise ApiError(403, "forbidden", "That faculty key is not valid.")


DB = Annotated[Session, Depends(get_db)]
