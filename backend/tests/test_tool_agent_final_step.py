"""The tool loop offers only the submit tool on its last step instead of running out of steps."""
from src.agents import llm_bridge, tool_agent
from src.agents.tools import ReviewTools
from tests.fixtures import review_cases as rc


def test_last_step_requires_submit(monkeypatch):
    monkeypatch.setattr(llm_bridge, "provider_name", lambda: "groq")
    monkeypatch.setattr(llm_bridge, "model_id", lambda: "m")
    offered = []

    def fake_converse(**kw):
        names = [t["toolSpec"]["name"] for t in kw["toolConfig"]["tools"]]
        offered.append(names)
        name = names[0]
        args = {"ok": True} if name == "submit_x" else {}
        return {"output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": f"t{len(offered)}", "name": name, "input": args}}]}}}

    monkeypatch.setattr(tool_agent, "_converse", fake_converse)
    tools = ReviewTools(rc.case_a_clean(), "proponent")
    result = tool_agent.run_tool_agent(
        tools=tools, system="s", user="u", tool_names=["list_evidence"], submit_name="submit_x",
        submit_description="d", submit_schema={"type": "object"}, validate=lambda a: a, max_steps=3)

    assert result == {"ok": True}
    assert offered == [["list_evidence", "submit_x"]] * 2 + [["submit_x"]]


def test_tools_ignore_arguments_they_do_not_take():
    tools = ReviewTools(rc.case_a_clean(), "challenger")
    out, ok = tools.call("get_mandate", {"case_id": "FG-1"})
    assert ok and "mandate" in out
