from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Milestone 8 Multi-Format Report Renderer
Renders ReportPayload instances into Markdown, HTML, JSON, and PDF documents.
Highlights citations and explicitly flags unverified statements with [⚠ PROVENANCE REVIEW REQUIRED].
"""
import html
import pathlib
from typing import Optional

from config import settings
from report.contracts import ProvenanceStatus, ReportPayload

REPORT_DIR = pathlib.Path(settings.report_output_dir)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

try:
    from weasyprint import HTML
except (ImportError, OSError):
    HTML = None


class ReportRenderer:
    """
    Renders structured ReportPayload objects into human-readable and court-admissible formats.
    """

    @staticmethod
    def to_markdown(payload: ReportPayload) -> str:
        """
        Renders report as structured GitHub-flavored Markdown.
        """
        meta = payload.metadata
        prov = payload.provenance_summary
        lines = []

        lines.append(f"# {meta.title}")
        lines.append("")
        lines.append(f"**Case:** {meta.case_number} ({meta.case_title})  ")
        lines.append(f"**State Version:** v{meta.case_state_version}  ")
        lines.append(f"**Report Type:** {meta.report_type.value.upper()}  ")
        lines.append(f"**Status:** {meta.status.value.upper()}  ")
        lines.append(f"**Generated:** {meta.generated_at}  ")
        lines.append(f"**Cryptographic Hash (SHA-256):** `{meta.content_hash}`  ")
        lines.append("")

        # Provenance summary banner
        if prov.get("has_warnings"):
            lines.append("> [!WARNING]")
            lines.append(f"> **PROVENANCE NOTICE:** {prov.get('review_required_claims')} of {prov.get('total_claims')} claims require review.")
            lines.append("> Some assertions lack fully grounded evidentiary citations.")
            lines.append("")
        else:
            lines.append("> [!NOTE]")
            lines.append(f"> **CRYPTOGRAPHICALLY GROUNDED:** All {prov.get('total_claims')} claims verified with exact bitstream citations.")
            lines.append("")

        for sec in payload.sections:
            lines.append(f"## {sec.title}")
            if sec.summary:
                lines.append(f"*{sec.summary}*")
                lines.append("")

            # Section claims
            if sec.claims:
                lines.append("### Claims & Evidentiary Findings")
                for c in sec.claims:
                    citations_str = " ".join(cit.citation_label for cit in c.evidence_refs) if c.evidence_refs else ""
                    warn_str = " **[⚠ PROVENANCE REVIEW REQUIRED]**" if c.provenance_status != ProvenanceStatus.VERIFIED else ""
                    lines.append(f"- **{c.claim_id}**: {c.text} {citations_str}{warn_str}")
                    if c.provenance_chain and c.provenance_chain.warnings:
                        for w in c.provenance_chain.warnings:
                            lines.append(f"  - *Warning:* {w}")
                lines.append("")

            # Limitations
            if sec.limitations:
                lines.append("### Section Limitations")
                for lim in sec.limitations:
                    lines.append(f"- ⚠ {lim}")
                lines.append("")

            lines.append("---")
            lines.append("")

        # Statutory appendix
        if payload.statutory_provisions:
            lines.append("## Statutory & Legal Mandate")
            for k, v in payload.statutory_provisions.items():
                lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def to_html(cls, payload: ReportPayload) -> str:
        """
        Renders report as clean, print-ready semantic HTML with legal notice styling.
        """
        meta = payload.metadata
        prov = payload.provenance_summary

        sections_html = []
        for sec in payload.sections:
            claims_li = []
            for c in sec.claims:
                cits_html = "".join(
                    f'<span class="citation-badge">{html.escape(cit.citation_label)}</span>'
                    for cit in c.evidence_refs
                )
                warn_badge = (
                    '<span class="warning-badge">⚠ PROVENANCE REVIEW REQUIRED</span>'
                    if c.provenance_status != ProvenanceStatus.VERIFIED
                    else '<span class="verified-badge">✓ VERIFIED</span>'
                )
                claims_li.append(
                    f'<li><strong>{html.escape(c.claim_id)}</strong>: {html.escape(c.text)} '
                    f'{cits_html} {warn_badge}</li>'
                )

            lims_li = "".join(f"<li>⚠ {html.escape(lim)}</li>" for lim in sec.limitations)
            lims_block = f'<div class="limitations-box"><h4>Limitations</h4><ul>{lims_li}</ul></div>' if lims_li else ""

            sections_html.append(f"""
            <section class="report-section">
                <h2>{html.escape(sec.title)}</h2>
                {f'<p class="sec-summary">{html.escape(sec.summary)}</p>' if sec.summary else ''}
                <ul class="claims-list">{''.join(claims_li)}</ul>
                {lims_block}
            </section>
            """)

        banner_class = "banner-warning" if prov.get("has_warnings") else "banner-success"
        banner_text = (
            f"⚠ PROVENANCE NOTICE: {prov.get('review_required_claims')} of {prov.get('total_claims')} claims require review."
            if prov.get("has_warnings")
            else f"✓ VERIFIED: {prov.get('total_claims')} claims verified with cryptographic bitstream citations."
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>{html.escape(meta.title)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 40px; color: #1e293b; line-height: 1.5; font-size: 13px; }}
  h1 {{ font-size: 20px; border-bottom: 2px solid #0f172a; padding-bottom: 8px; margin-bottom: 4px; }}
  h2 {{ font-size: 15px; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; margin-top: 24px; color: #0f172a; }}
  h4 {{ font-size: 12px; margin: 6px 0; color: #b45309; }}
  .header-meta {{ font-size: 11px; color: #64748b; margin-bottom: 20px; font-family: monospace; }}
  .banner {{ padding: 10px 14px; border-radius: 6px; font-weight: bold; margin-bottom: 24px; font-size: 12px; }}
  .banner-success {{ background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }}
  .banner-warning {{ background: #fffbeb; color: #92400e; border: 1px solid #fde68a; }}
  .citation-badge {{ display: inline-block; background: #eff6ff; color: #1d4ed8; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-family: monospace; border: 1px solid #bfdbfe; margin: 0 2px; }}
  .warning-badge {{ display: inline-block; background: #fee2e2; color: #b91c1c; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; border: 1px solid #fca5a5; margin: 0 4px; }}
  .verified-badge {{ display: inline-block; background: #dcfce7; color: #15803d; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; border: 1px solid #86efac; margin: 0 4px; }}
  .limitations-box {{ background: #fefce8; border: 1px solid #fef08a; padding: 8px 12px; border-radius: 4px; margin-top: 12px; font-size: 11px; }}
  .claims-list {{ padding-left: 20px; }}
  .claims-list li {{ margin-bottom: 8px; }}
  .footer {{ margin-top: 40px; font-size: 10px; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 12px; }}
</style>
</head>
<body>
  <h1>{html.escape(meta.title)}</h1>
  <div class="header-meta">
    Case: {html.escape(meta.case_number)} · State v{meta.case_state_version} · Hash: {html.escape(meta.content_hash[:16])}... · Generated: {html.escape(meta.generated_at)}
  </div>

  <div class="banner {banner_class}">{banner_text}</div>

  {''.join(sections_html)}

  <div class="footer">
    CyberDrishti AI / NETRA V5 — Admissibility aid under Section 63 BSA, 2023 / Section 65B IEA. Document hash: {html.escape(meta.content_hash)}.
  </div>
</body>
</html>"""

    @classmethod
    async def render_pdf(cls, payload: ReportPayload) -> pathlib.Path:
        """
        Renders HTML to PDF using WeasyPrint (or writes HTML if WeasyPrint unavailable).
        """
        html_content = cls.to_html(payload)
        filename = f"report_{payload.metadata.report_id}.pdf"
        out_path = REPORT_DIR / filename

        if HTML:
            HTML(string=html_content).write_pdf(str(out_path))
        else:
            # Fallback to HTML if WeasyPrint native libs are missing
            html_path = REPORT_DIR / f"report_{payload.metadata.report_id}.html"
            html_path.write_text(html_content, encoding="utf-8")
            return html_path

        return out_path
