import json
from json import JSONDecodeError
from typing import Union

from langchain_core.agents import AgentAction, AgentActionMessageLog, AgentFinish
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ToolCall,
)
from langchain_core.outputs import ChatGeneration, Generation
from typing_extensions import override

from langchain.agents.agent import MultiActionAgentOutputParser


class ToolAgentAction(AgentActionMessageLog):
    """ "Tool agent action."""

    tool_call_id: str
    """Tool call that this message is responding to."""


def parse_ai_message_to_tool_action(
    message: BaseMessage,
) -> Union[list[AgentAction], AgentFinish]:
    """Parse an AI message potentially containing tool_calls."""
    if not isinstance(message, AIMessage):
        msg = f"Expected an AI message got {type(message)}"
        raise TypeError(msg)

    actions: list = []
    if message.tool_calls:
        tool_calls = message.tool_calls
    else:
        if not message.additional_kwargs.get("tool_calls"):
            return AgentFinish(
                return_values={"output": message.content},
                log=str(message.content),
            )
        # Best-effort parsing
        tool_calls = []
        for tool_call in message.additional_kwargs["tool_calls"]:
            function = tool_call["function"]
            function_name = function["name"]
            try:
                args = json.loads(function["arguments"] or "{}")
                tool_calls.append(
                    ToolCall(name=function_name, args=args, id=tool_call["id"]),
                )
            except JSONDecodeError as e:
                msg = (
                    f"Could not parse tool input: {function} because "
                    f"the `arguments` is not valid JSON."
                )
                raise OutputParserException(msg) from e
    for tool_call in tool_calls:
        # HACK HACK HACK:
        # The code that encodes tool input into Open AI uses a special variable
        # name called `__arg1` to handle old style tools that do not expose a
        # schema and expect a single string argument as an input.
        # We unpack the argument here if it exists.
        # Open AI does not support passing in a JSON array as an argument.
        function_name = tool_call["name"]
        _tool_input = tool_call["args"]
        tool_input = _tool_input.get("__arg1", _tool_input)

        content_msg = f"responded: {message.content}\n" if message.content else "\n"
        log = f"\nInvoking: `{function_name}` with `{tool_input}`\n{content_msg}\n"
        actions.append(
            ToolAgentAction(
                tool=function_name,
                tool_input=tool_input,
                log=log,
                message_log=[message],
                tool_call_id=tool_call["id"],
            ),
        )
    return actions


class ToolsAgentOutputParser(MultiActionAgentOutputParser):
    """Parses a message into agent actions/finish.

    If a tool_calls parameter is passed, then that is used to get
    the tool names and tool inputs.

    If one is not passed, then the AIMessage is assumed to be the final output.
    """

    @property
    def _type(self) -> str:
        return "tools-agent-output-parser"

    @override
    def parse_result(
        self,
        result: list[Generation],
        *,
        partial: bool = False,
    ) -> Union[list[AgentAction], AgentFinish]:
        if not isinstance(result[0], ChatGeneration):
            msg = "This output parser only works on ChatGeneration output"
            raise ValueError(msg)  # noqa: TRY004
        message = result[0].message
        return parse_ai_message_to_tool_action(message)

    @override
    def parse(self, text: str) -> Union[list[AgentAction], AgentFinish]:
        msg = "Can only parse messages"
        raise ValueError(msg)
