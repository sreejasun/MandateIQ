"""
MandateIQ Adaptive Orchestration Graph.

Owner: Narahari

This module coordinates execution of MandateIQ workflow stages.

The graph does not implement Data Steward, Proponent, Challenger,
Policy, Hallucination Firewall, or Trust Score business logic.
Instead, those modules are injected through shared callable contracts.

This allows each teammate to develop independently while preserving
one shared WorkflowState and one adaptive orchestration layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from config.settings import MandateIQSettings, load_settings
from src.agents.supervisor import run_supervisor
from src.orchestration.routing import (
    Route,
    RoutingConfig,
    routing_config_from_settings,
)
from src.orchestration.state import WorkflowState


# ============================================================
# TYPE ALIASES
# ============================================================

WorkflowNode = Callable[[WorkflowState], WorkflowState]


# ============================================================
# GRAPH DEPENDENCIES
# ============================================================

@dataclass
class WorkflowDependencies:
    """
    Functions supplied by MandateIQ specialist modules.

    These contracts allow the orchestration graph to operate without
    owning another teammate's implementation.
    """

    run_data_steward: WorkflowNode

    run_proponent: WorkflowNode

    run_challenger: WorkflowNode

    run_policy_review: WorkflowNode

    verify_claims: WorkflowNode

    calculate_trust_score: WorkflowNode

    run_reanalysis: WorkflowNode | None = None

    request_more_evidence: WorkflowNode | None = None


# ============================================================
# GRAPH RESULT
# ============================================================

@dataclass
class WorkflowRunResult:
    """
    Result returned after one orchestration run.
    """

    state: WorkflowState

    completed: bool

    terminal_route: Route | None

    steps_executed: int


# ============================================================
# GRAPH
# ============================================================

class MandateIQGraph:
    """
    Adaptive MandateIQ orchestration engine.

    The Supervisor determines what should happen next based on the
    current WorkflowState.

    The graph executes the selected node and then returns control to
    the Supervisor.

    Therefore, cases are not forced through one fixed linear path.

    Runtime routing thresholds and workflow safety limits are loaded
    from centralized MandateIQ settings unless explicitly overridden.
    """

    def __init__(
        self,
        dependencies: WorkflowDependencies,
        routing_config: RoutingConfig | None = None,
        max_steps: int | None = None,
        settings: MandateIQSettings | None = None,
    ) -> None:
        """
        Initialize the MandateIQ graph.

        Args:
            dependencies:
                Implementations of specialist workflow modules.

            routing_config:
                Optional explicit routing configuration. When omitted,
                routing thresholds are created from MandateIQSettings.

            max_steps:
                Optional explicit workflow safety limit. When omitted,
                max_workflow_steps is loaded from MandateIQSettings.

            settings:
                Optional centralized MandateIQ settings object.
                When omitted, settings are loaded from environment
                variables using load_settings().
        """

        # ----------------------------------------------------
        # Centralized runtime configuration
        # ----------------------------------------------------

        self.settings = (
            settings
            or load_settings()
        )

        self.routing_config = (
            routing_config
            or routing_config_from_settings(
                self.settings
            )
        )

        self.max_steps = (
            max_steps
            if max_steps is not None
            else self.settings.max_workflow_steps
        )

        if self.max_steps <= 0:
            raise ValueError(
                "max_steps must be greater than zero"
            )

        self.dependencies = dependencies


    # ========================================================
    # PUBLIC EXECUTION METHOD
    # ========================================================

    def run(
        self,
        state: WorkflowState,
    ) -> WorkflowRunResult:
        """
        Execute MandateIQ until a terminal route is reached.

        Terminal routes:

            FINALIZE
            HUMAN_REVIEW

        Non-terminal routes execute the corresponding workflow node,
        update WorkflowState, and return control to the Supervisor.
        """

        steps = 0

        # ----------------------------------------------------
        # Initial Data Steward execution
        # ----------------------------------------------------

        if not self._data_steward_completed(state):

            state = self._execute_node(
                node=self.dependencies.run_data_steward,
                state=state,
                node_name="data_steward",
            )

            steps += 1

        # ----------------------------------------------------
        # Adaptive Supervisor loop
        # ----------------------------------------------------

        while steps < self.max_steps:

            supervisor_result = run_supervisor(
                state=state,
                config=self.routing_config,
            )

            steps += 1

            route = supervisor_result.route

            # ------------------------------------------------
            # Terminal routes
            # ------------------------------------------------

            if route == Route.FINALIZE:

                return WorkflowRunResult(
                    state=state,
                    completed=True,
                    terminal_route=Route.FINALIZE,
                    steps_executed=steps,
                )

            if route == Route.HUMAN_REVIEW:

                return WorkflowRunResult(
                    state=state,
                    completed=True,
                    terminal_route=Route.HUMAN_REVIEW,
                    steps_executed=steps,
                )

            # ------------------------------------------------
            # Specialist workflow routes
            # ------------------------------------------------

            if route == Route.DATA_REMEDIATION:

                state = self._execute_node(
                    node=self.dependencies.run_data_steward,
                    state=state,
                    node_name="data_remediation",
                )

                steps += 1

                continue

            if route == Route.PROPONENT:

                state = self._execute_node(
                    node=self.dependencies.run_proponent,
                    state=state,
                    node_name="proponent",
                )

                steps += 1

                continue

            if route == Route.CHALLENGER:

                state = self._execute_node(
                    node=self.dependencies.run_challenger,
                    state=state,
                    node_name="challenger",
                )

                steps += 1

                continue

            if route == Route.POLICY_REVIEW:

                state = self._execute_node(
                    node=self.dependencies.run_policy_review,
                    state=state,
                    node_name="policy_review",
                )

                steps += 1

                continue

            if route == Route.VERIFY_CLAIMS:

                state = self._execute_node(
                    node=self.dependencies.verify_claims,
                    state=state,
                    node_name="verify_claims",
                )

                steps += 1

                # Trust Score depends on verified claims and therefore
                # runs after the firewall/verification stage.

                state = self._execute_node(
                    node=self.dependencies.calculate_trust_score,
                    state=state,
                    node_name="trust_score",
                )

                steps += 1

                continue

            if route == Route.REANALYSIS:

                if self.dependencies.run_reanalysis is None:

                    state.human_review_required = True

                    state.human_review_reason = (
                        "Re-analysis was requested but no "
                        "re-analysis handler is configured."
                    )

                    continue

                state = self._execute_node(
                    node=self.dependencies.run_reanalysis,
                    state=state,
                    node_name="reanalysis",
                )

                steps += 1

                continue

            if route == Route.MORE_EVIDENCE:

                if (
                    self.dependencies.request_more_evidence
                    is None
                ):

                    state.human_review_required = True

                    state.human_review_reason = (
                        "Additional evidence is required but "
                        "no evidence-request handler is configured."
                    )

                    continue

                state = self._execute_node(
                    node=self.dependencies.request_more_evidence,
                    state=state,
                    node_name="more_evidence",
                )

                steps += 1

                continue

            # ------------------------------------------------
            # Defensive fallback
            # ------------------------------------------------

            raise RuntimeError(
                f"Unsupported workflow route: {route}"
            )

        # ----------------------------------------------------
        # Safety limit reached
        # ----------------------------------------------------

        state.human_review_required = True

        state.human_review_reason = (
            "Workflow exceeded the configured maximum "
            f"step count of {self.max_steps}."
        )

        # Record the safety escalation through the Supervisor.

        supervisor_result = run_supervisor(
            state=state,
            config=self.routing_config,
        )

        return WorkflowRunResult(
            state=state,
            completed=True,
            terminal_route=supervisor_result.route,
            steps_executed=steps,
        )


    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    @staticmethod
    def _data_steward_completed(
        state: WorkflowState,
    ) -> bool:
        """
        Determine whether Data Steward output already exists.

        This allows pre-seeded or resumed workflow states to enter
        the graph without unnecessarily repeating ingestion.
        """

        return bool(
            state.quality_report
            or state.data_profile
            or state.metadata
            or state.quality_score > 0
        )


    @staticmethod
    def _execute_node(
        node: WorkflowNode,
        state: WorkflowState,
        node_name: str,
    ) -> WorkflowState:
        """
        Execute one workflow node and validate its contract.

        Every node must return WorkflowState.
        """

        result = node(state)

        if not isinstance(
            result,
            WorkflowState,
        ):
            raise TypeError(
                f"Workflow node '{node_name}' must "
                "return WorkflowState."
            )

        return result