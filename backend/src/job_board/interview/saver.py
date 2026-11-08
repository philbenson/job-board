"""Where the interview graph keeps its steps: LangGraph's PostgreSQL saver, on a pool of its own.

Invariant: a saved step is read back only into the types the graph's state
and its pending writes hold. The serializer is strict: a saved value naming
any other type is left as its raw fields and never constructed, and pickle is
off, so a row in these tables cannot make loading it run code.

The tables are the migrations'; nothing here creates or alters them (see
``tests/test_checkpoint_tables.py``).
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.types import Interrupt
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import make_url

# The messages, and the question an interview waits on: every type a saved
# step names. A step holding any other type fails the tests, rather than
# coming back as a bare dictionary of its fields.
STATE_TYPES = (AIMessage, HumanMessage, ToolMessage, Interrupt)
POOL_MIN_SIZE = 1  # one connection kept open for the next step to save
# A step holds a connection only while it saves, so a few serve every
# interview this process runs at once.
POOL_MAX_SIZE = 4
POOL_NAME = "interview-saver"  # names the pool in psycopg's own log lines

type SaverPool = AsyncConnectionPool[AsyncConnection[DictRow]]


def libpq_url(database_url: str) -> str:
    """The service's database URL in the form psycopg takes, without SQLAlchemy's driver name."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


def saver_pool(database_url: str) -> SaverPool:
    """The saver's pool, not yet open: the lifespan opens it and closes it."""
    return AsyncConnectionPool(
        libpq_url(database_url),
        connection_class=AsyncConnection[DictRow],
        # What the saver's queries need: each statement its own transaction,
        # no server-side prepared statements, and rows read by column name.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        name=POOL_NAME,
        check=AsyncConnectionPool.check_connection,
        open=False,
    )


def interview_saver(pool: SaverPool) -> AsyncPostgresSaver:
    """The saver over ``pool``, strict about what it reads back.

    LangGraph's saver takes the running loop when it is built, so build it inside that loop.
    """
    serializer = JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=STATE_TYPES)
    return AsyncPostgresSaver(pool, serde=serializer)
