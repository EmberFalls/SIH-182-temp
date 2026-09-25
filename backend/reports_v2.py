"""PDF rendering from an immutable v2 InvestigationResult snapshot."""
from __future__ import annotations

from io import BytesIO
from textwrap import wrap

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from .domain import InvestigationCaseV2, InvestigationResultV2


class InvestigationResultReportV2:
    """Renders answers in investigation order; graph data stays supporting evidence."""

    def render(self, case: InvestigationCaseV2, result: InvestigationResultV2) -> bytes:
        stream = BytesIO()
        canvas = Canvas(stream, pagesize=A4, pageCompression=1)
        width, height = A4
        y = height - 126

        def footer() -> None:
            canvas.setFillColor(HexColor("#64748b"))
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(width - 42, 28, f"VASP Trace v2 | Result {result.id} | Page {canvas.getPageNumber()}")

        def safe_text(value: object) -> str:
            """Built-in ReportLab fonts are deliberately used for portable PDFs."""
            return str(value).replace("—", "-").replace("–", "-").encode("latin-1", "replace").decode("latin-1")

        def line(value: str, size: int = 9, indent: int = 42, color=HexColor("#172033")) -> None:
            nonlocal y
            canvas.setFillColor(color)
            canvas.setFont("Helvetica", size)
            for part in wrap(safe_text(value), width=104 if size <= 9 else 82, break_long_words=False, break_on_hyphens=False) or [""]:
                if y < 56:
                    footer()
                    canvas.showPage()
                    y = height - 52
                canvas.drawString(indent, y, part)
                y -= size + 5

        def heading(value: str) -> None:
            nonlocal y
            if y < 92:
                footer()
                canvas.showPage()
                y = height - 52
            canvas.setFillColor(HexColor("#0f766e"))
            canvas.setFont("Helvetica-Bold", 13)
            canvas.drawString(42, y, value)
            y -= 23

        canvas.setFillColor(HexColor("#0f172a"))
        canvas.rect(0, height - 98, width, 98, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#f8fafc"))
        canvas.setFont("Helvetica-Bold", 20)
        canvas.drawString(42, height - 50, "VASP TRACE")
        canvas.setFont("Helvetica", 10)
        canvas.drawString(42, height - 70, "Investigation result - evidence-grounded VASP attribution")

        heading("1. Analysis scope")
        context = case.context
        seed = context.seed_tx_hash or context.seed_wallet or "Not supplied"
        line(f"Case: {case.id} | {case.title}")
        line(f"Result: {result.id} version {result.version} | Generated: {result.generated_at.isoformat()}")
        line(f"Data mode: {result.data_mode.value} | Chain: {context.chain.value} | Asset: {context.asset.symbol}")
        line(f"Seed ({context.seed_type.value}): {seed}")
        line(f"Disputed amount: {context.disputed_amount} {context.asset.symbol} | Incident time: {context.incident_time.isoformat()}")

        heading("2. Trace accounting")
        accounted = result.flow.terminal_amount
        line(f"Seed amount: {result.flow.seed_amount} {context.asset.symbol}; terminal-accounted: {accounted}; retained: {result.flow.retained_amount}; unresolved: {result.flow.unresolved_amount}.")
        line(f"Seed precision: {result.flow.seed_precision.value}; allocation policy: {result.flow.allocation_policy.value}.")

        heading("3. Actionable VASP endpoints")
        if result.attribution.candidates:
            for candidate in result.attribution.candidates:
                line(f"{candidate.entity_name} - {candidate.status.value}; {candidate.attributed_amount} {context.asset.symbol}; {candidate.disputed_share * 100}% of seed; minimum hops {candidate.min_hops}.")
                line(f"Terminal address(es): {', '.join(candidate.terminal_addresses)} | roles: {', '.join(role.value for role in candidate.terminal_roles)}", indent=56)
        else:
            line("No VASP endpoint met the configured evidence threshold. The result remains unresolved.")

        heading("4. Attribution evidence")
        for candidate in result.attribution.candidates:
            components = candidate.attribution_evidence
            line(f"{candidate.entity_name}: evidence score {candidate.attribution_evidence_score}/100 ({candidate.attribution_band.value}); exact label {components.exact_reviewed_label}, cluster relation {components.cluster_relationship}, deposit behavior {components.deposit_behavior}, corroboration {components.independent_corroboration}, freshness {components.freshness}.")
            line(f"Evidence IDs: {', '.join(candidate.evidence_ids)}", indent=56)

        heading("5. Relevant transaction paths")
        for candidate in result.attribution.candidates:
            line(f"{candidate.entity_name}: path IDs {', '.join(candidate.path_ids) or 'None'}.")
        for allocation in result.flow.allocations:
            line(f"{allocation.transfer_id}: {allocation.source_address} -> {allocation.destination_address}; attributed {allocation.attributed_disputed_amount} {context.asset.symbol}; depth {allocation.depth}.", indent=56)

        heading("6. Unresolved value and boundaries")
        line(f"Unresolved amount: {result.attribution.unresolved_amount} {context.asset.symbol}.")
        for terminal in result.flow.terminals:
            if terminal.reason.value not in {"VERIFIED_VASP", "INFERRED_VASP_DEPOSIT"}:
                line(f"{terminal.reason.value}: {terminal.address}; {terminal.amount} {context.asset.symbol}. {terminal.detail}", indent=56)

        heading("7. Methodology and limitations")
        for key, value in result.methodology.items():
            line(f"{key}: {value}")
        for limitation in result.limitations:
            line(f"- {limitation}")

        heading("8. Machine-generated inferences")
        if result.deposit_inferences:
            for inference in result.deposit_inferences:
                line(f"{inference.address}: probable {inference.inferred_role.value} for {inference.candidate_entity_name}; rule evidence score {inference.evidence_score}/100; review required.")
                line(f"Reasons: {'; '.join(inference.reasons)}", indent=56)
        else:
            line("No rule or ML inference was included in this result.")

        heading("9. Data sources and manifest")
        line(f"Evidence manifest SHA-256: {result.evidence_manifest.sha256}")
        for entry in result.evidence_manifest.evidence:
            line(f"{entry.kind}: {entry.id}; provider {entry.provider}; retrieved {entry.retrieved_at.isoformat() if entry.retrieved_at else 'not supplied'}; SHA-256 {entry.sha256}.", indent=56)
        line("This report records public-chain observations and sourced evidence. It does not establish beneficial ownership, authorize a freeze, or submit any request to SAHYOG or a VASP.")
        footer()
        canvas.save()
        return stream.getvalue()