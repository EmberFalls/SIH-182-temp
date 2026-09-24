"""Investigation-ready PDF rendering from an immutable saved trace run."""
from io import BytesIO
from textwrap import wrap
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from .models import CaseSummary, TraceResult


class InvestigationReport:
    def render(self, case: CaseSummary, trace: TraceResult) -> bytes:
        stream = BytesIO()
        canvas = Canvas(stream, pagesize=A4, pageCompression=1)
        width, height = A4
        y = height - 48

        def line(text: str, size: int = 9, color=HexColor("#172033"), indent: int = 42) -> None:
            nonlocal y
            canvas.setFillColor(color)
            canvas.setFont("Helvetica", size)
            maximum = 105 if size <= 9 else 78
            for fragment in wrap(str(text), width=maximum, break_long_words=False, break_on_hyphens=False) or [""]:
                if y < 50:
                    canvas.setFont("Helvetica", 8)
                    canvas.setFillColor(HexColor("#64748b"))
                    canvas.drawRightString(width - 42, 28, f"VASP Trace evidence report | Page {canvas.getPageNumber()}")
                    canvas.showPage()
                    y = height - 48
                canvas.drawString(indent, y, fragment)
                y -= size + 5

        def heading(text: str) -> None:
            nonlocal y
            if y < 85:
                canvas.showPage()
                y = height - 48
            canvas.setFillColor(HexColor("#0f766e"))
            canvas.setFont("Helvetica-Bold", 13)
            canvas.drawString(42, y, text)
            y -= 24

        canvas.setFillColor(HexColor("#0f172a"))
        canvas.rect(0, height - 98, width, 98, fill=1, stroke=0)
        canvas.setFillColor(HexColor("#f8fafc"))
        canvas.setFont("Helvetica-Bold", 20)
        canvas.drawString(42, height - 50, "VASP TRACE")
        canvas.setFont("Helvetica", 10)
        canvas.drawString(42, height - 70, "Evidence-grounded virtual asset service provider attribution report")
        y = height - 126

        heading("Case and trace scope")
        line(f"Case: {case.id} | {case.title}")
        line(f"FIR: {case.fir_number or 'Not supplied'} | Chain: {case.chain.value} | Token: {case.token_symbol}")
        line(f"Suspect wallet: {case.suspect_wallet}")
        line(f"Trace run: {trace.run_id} | Data mode: {trace.provenance.get('data_mode', 'UNKNOWN')} | Status: {trace.status}")
        line(f"Created: {trace.created_at.isoformat()} | Manifest SHA-256: {trace.manifest_sha256}")

        heading("Attribution findings")
        if trace.candidates:
            for candidate in trace.candidates:
                line(f"{candidate.vasp_name}: priority {candidate.priority_score}/100, {candidate.attributed_amount} {case.token_symbol}, hop {candidate.hop}.")
                line(f"Address: {candidate.address}; transaction: {candidate.supporting_transaction}; {candidate.ranking_reason}", indent=56)
        else:
            line("No supported VASP endpoint was found within the examined trace. This result is unresolved and must not be interpreted as an ownership finding.")

        heading("Fund-flow allocation")
        if trace.flow_analysis:
            flow = trace.flow_analysis
            line(f"Starting disputed amount: {flow.starting_amount} {case.token_symbol}; allocated from source: {flow.allocated_amount}; unallocated: {flow.unallocated_amount}.")
            line(flow.method_note)
            for allocation in flow.allocations[:20]:
                line(f"{allocation.source_address} -> {allocation.destination_address}: {allocation.attributed_amount}/{allocation.transfer_amount} {case.token_symbol}; tx {allocation.transaction_hash}", indent=56)
        else:
            line("No flow allocation was available.")

        heading("Risk and cross-chain observations")
        for alert in trace.risk_alerts:
            line(f"{alert.severity.upper()}: {alert.description} Transactions: {', '.join(alert.supporting_transactions)}")
        for bridge in trace.bridge_observations:
            line(f"Bridge observation: {bridge.bridge_name}, source transaction {bridge.transaction_hash}. Next evidence needed: {bridge.next_evidence_needed}")
        if not trace.risk_alerts and not trace.bridge_observations:
            line("No rule-based risk or bridge observations were triggered within the examined scope.")

        heading("Limitations and investigator review")
        for limitation in trace.limitations:
            line(f"- {limitation}")
        line("This report records public-chain observations and sourced labels. It does not establish beneficial ownership, authorize a freeze, or replace investigator and legal review.")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(HexColor("#64748b"))
        canvas.drawRightString(width - 42, 28, f"VASP Trace evidence report | Page {canvas.getPageNumber()}")
        canvas.save()
        return stream.getvalue()
