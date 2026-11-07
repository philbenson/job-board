"""The graph that rates one posting: one node, compiled once.

The model, built per batch on that person's key, reaches the node through the
run's context rather than its state, so it is never part of what the graph
reads, returns or could keep.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypedDict

from langchain_core.exceptions import ModelRefusalError, OutputParserException
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from job_board.scoring.model import Rating, RatingModel
from job_board.scoring.prompt import prompt_messages


@dataclass(frozen=True)
class Context:
    model: RatingModel


class State(TypedDict, total=False):
    titles: list[str]
    text: str
    # None when the reply could not be read as a rating.
    rating: Rating | None


async def _rate(state: State, runtime: Runtime[Context]) -> State:
    """Ask the model; a reply that is no valid rating is no rating.

    Such a reply is not retried: the same prompt would likely get the same
    answer, and each try costs the person. The parser's exception quotes the
    reply, so it is dropped here, never logged. A failed request raises.
    """
    try:
        reply = await runtime.context.model.ainvoke(prompt_messages(state["titles"], state["text"]))
    except OutputParserException, ModelRefusalError:
        return {"rating": None}
    return {"rating": reply if isinstance(reply, Rating) else None}


def _build() -> CompiledStateGraph[State, Context, State, State]:
    builder = StateGraph(State, context_schema=Context)
    builder.add_node("rate", _rate)
    builder.add_edge(START, "rate")
    builder.add_edge("rate", END)
    return builder.compile()


RATING_GRAPH = _build()


async def rate(model: RatingModel, titles: Sequence[str], text: str) -> Rating | None:
    """The model's rating of one posting's ``text`` against ``titles``, or None."""
    result = await RATING_GRAPH.ainvoke(
        {"titles": list(titles), "text": text}, context=Context(model=model)
    )
    rating: Rating | None = result.get("rating")
    return rating
