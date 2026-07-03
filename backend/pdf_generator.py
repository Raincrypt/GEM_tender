from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import io
from datetime import datetime

def generate_comparative_pdf(tender_data, bids_data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        rightMargin=30, leftMargin=30,
        topMargin=30, bottomMargin=18
    )
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#1d4ed8'),
        alignment=1, # Center
        spaceAfter=20
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Heading3'],
        fontSize=12,
        textColor=colors.HexColor('#475569'),
        spaceAfter=30
    )
    
    # Header
    elements.append(Paragraph(f"GEM Tender - Advanced Comparative Statement", title_style))
    elements.append(Paragraph(f"Bid Reference: <b>{tender_data['bid_number']}</b> | Title: {tender_data['title']}", subtitle_style))
    
    # Summary Table
    elements.append(Paragraph("Tender Summary", styles['Heading2']))
    summary_data = [
        ['Total Estimated Value', f"Rs. {tender_data['estimated_value']:,.2f}" if tender_data['estimated_value'] else 'N/A'],
        ['Evaluation Weightage', f"Technical: {tender_data['technical_weightage']}% | Financial: {tender_data['financial_weightage']}%"],
        ['Total Bids Received', str(len(bids_data))]
    ]
    summary_table = Table(summary_data, colWidths=[2*inch, 4*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f8fafc')),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#0f172a')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1'))
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))
    
    # Bids Table
    elements.append(Paragraph("Detailed Bidder Evaluation Matrix", styles['Heading2']))
    
    headers = [
        'Rank', 'Vendor Name', 'Reg No', 'MSME/MII', 
        'Tech Score', 'Fin Score', 'Composite', 'Bid Amount (Rs.)', 'Status'
    ]
    
    table_data = [headers]
    for b in bids_data:
        vendor_details = f"{b['vendor_name']}\n({b['gem_reg_no']})"
        tags = []
        if b['msme']: tags.append("MSME")
        if b['make_in_india']: tags.append("MII")
        tags_str = ", ".join(tags) if tags else "None"
        
        status_text = "Disqualified" if b['is_disqualified'] else b['status']
        rank = "DQ" if b['is_disqualified'] else f"L{b['rank']}"
        
        row = [
            rank,
            b['vendor_name'],
            b['gem_reg_no'],
            tags_str,
            f"{b['technical_score']:.2f}",
            f"{b['financial_score']:.2f}",
            f"{b['composite_score']:.2f}",
            f"{b['total_amount']:,.2f}",
            status_text
        ]
        table_data.append(row)
        
    bids_table = Table(table_data, colWidths=[0.5*inch, 2*inch, 1*inch, 0.8*inch, 0.8*inch, 0.8*inch, 0.8*inch, 1.2*inch, 1*inch])
    bids_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e293b')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('BOTTOMPADDING', (0,0), (-1,0), 10),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
        ('TEXTCOLOR', (0,1), (-1,-1), colors.HexColor('#0f172a')),
        ('ALIGN', (0,1), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        # Highlight L1
        ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#dcfce7')), # Light green for L1
    ]))
    
    elements.append(bids_table)
    elements.append(Spacer(1, 30))
    
    # Signature Section
    elements.append(Paragraph("System Generated Report - GEM Tender Evaluation Framework", subtitle_style))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_contract_pdf(tender_data, vendor_data, bid_amount):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=40, leftMargin=40,
        topMargin=40, bottomMargin=40
    )
    
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'ContractTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#0f172a'),
        alignment=1,
        spaceAfter=30
    )
    
    elements.append(Paragraph("AWARD OF CONTRACT / LETTER OF INTENT", title_style))
    elements.append(Spacer(1, 20))
    
    content = f"""
    <b>Date:</b> {datetime.utcnow().strftime('%Y-%m-%d')}<br/><br/>
    <b>To:</b> {vendor_data['company_name']} ({vendor_data['gem_reg_no']})<br/><br/>
    <b>Subject:</b> Award of Contract for Tender Ref: {tender_data['bid_number']}<br/><br/>
    Dear Sir/Madam,<br/><br/>
    This is to formally notify you that your bid for the tender titled <b>"{tender_data['title']}"</b> 
    has been accepted by the competent authority.<br/><br/>
    The finalized total contract value is <b>Rs. {bid_amount:,.2f}</b>.<br/><br/>
    You are requested to formally acknowledge this letter of intent within 7 days and submit the required 
    Performance Security as per the tender terms.<br/><br/><br/><br/>
    <b>Authorized Signatory</b><br/>
    GEM Tender Administration Framework
    """
    
    elements.append(Paragraph(content, styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_dossier_pdf(dossier_data, pqc_data):
    """
    Generates a highly professional, comprehensive print-ready PDF audit dossier
    containing comparative matrices, deep-dive QCBS, PQC compliance audits,
    AI threat scanner details, and blockchain timelines.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=36, leftMargin=36,
        topMargin=36, bottomMargin=36
    )
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#0f172a'),
        alignment=1, # Center
        spaceAfter=15
    )
    
    section_heading = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=colors.HexColor('#1d4ed8'),
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )
    
    text_normal = ParagraphStyle(
        'TextNormal',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#334155')
    )
    
    text_bold = ParagraphStyle(
        'TextBold',
        parent=text_normal,
        fontName='Helvetica-Bold'
    )
    
    code_style = ParagraphStyle(
        'CodeStyle',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor('#475569')
    )

    # ── Page 1: Title & Executive Summary ──
    elements.append(Paragraph("TENDER AUDIT & COMPLIANCE DOSSIER", title_style))
    elements.append(Paragraph("<b>GEM Intelligent Procurement Autopilot Framework</b>", ParagraphStyle('Sub', parent=styles['Normal'], fontSize=10, alignment=1, textColor=colors.HexColor('#475569'), spaceAfter=20)))
    
    # Metadata Block Table
    tender = dossier_data.get("tender", {})
    savings = dossier_data.get("savings", {})
    
    meta_data = [
        [Paragraph("Tender Bid Number:", text_bold), Paragraph(tender.get("bid_number", "N/A"), text_normal),
         Paragraph("Total Estimated Value:", text_bold), Paragraph(f"Rs. {tender.get('estimated_value', 0):,.2f}" if tender.get("estimated_value") else "N/A", text_normal)],
        [Paragraph("Tender Title:", text_bold), Paragraph(tender.get("title", "N/A"), text_normal),
         Paragraph("Procurement Status:", text_bold), Paragraph(tender.get("status", "N/A"), text_normal)],
        [Paragraph("Taxpayer Savings:", text_bold), Paragraph(f"Rs. {savings.get('amount', 0):,.2f} ({savings.get('percentage', 0)}%)", text_bold if savings.get("amount", 0) > 0 else text_normal),
         Paragraph("Audit Generated At:", text_bold), Paragraph(datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'), text_normal)]
    ]
    
    meta_table = Table(meta_data, colWidths=[1.3*inch, 2.2*inch, 1.4*inch, 2.1*inch])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1'))
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 15))
    
    # Executive AI Summary Card
    elements.append(Paragraph("Executive AI Summary", section_heading))
    summary_box = Table([[Paragraph(dossier_data.get("ai_summary", "No summary generated."), text_normal)]], colWidths=[7.0*inch])
    summary_box.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#eff6ff')), # light blue
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
        ('RIGHTPADDING', (0,0), (-1,-1), 12),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor('#3b82f6')) # blue border
    ]))
    elements.append(summary_box)
    elements.append(Spacer(1, 15))

    # ── Section 1: Detailed Evaluation Matrix ──
    elements.append(Paragraph("Section 1: Detailed Vendor Evaluation Matrix", section_heading))
    
    matrix_headers = [
        Paragraph("Rank/Status", text_bold),
        Paragraph("Vendor Name", text_bold),
        Paragraph("Technical Score", text_bold),
        Paragraph("Financial Bid (Rs.)", text_bold),
        Paragraph("AI Trust Score", text_bold)
    ]
    matrix_data = [matrix_headers]
    
    comparisons = dossier_data.get("comparisons", [])
    for c in comparisons:
        status_suffix = f" ({c['status']})" if c['status'] == 'Awarded' else ''
        rank_str = f"L1{status_suffix}" if c['status'] == 'Awarded' else ("DQ" if c['status'].lower().startswith('disq') else f"L{comparisons.index(c) + 1 if c in comparisons else ''}")
        
        row = [
            Paragraph(rank_str, text_bold if c['status'] == 'Awarded' else text_normal),
            Paragraph(f"<b>{c['vendor_name']}</b><br/><font color='#64748b' size='8'>Reg: {c['gem_reg_no']}</font>", text_normal),
            Paragraph(f"{c['tech_score']:.2f} / 100", text_normal),
            Paragraph(f"Rs. {c['financial_amount']:,.2f}", text_normal),
            Paragraph(f"{c['trust_score']:.1f} / 100", text_normal)
        ]
        matrix_data.append(row)
        
    matrix_table = Table(matrix_data, colWidths=[1.2*inch, 2.5*inch, 1.1*inch, 1.2*inch, 1.0*inch])
    matrix_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e293b')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#ffffff'))
    ]))
    # Apply light green highlighting for awarded L1
    for idx, c in enumerate(comparisons):
        if c['status'] == 'Awarded':
            matrix_table.setStyle(TableStyle([('BACKGROUND', (0, idx + 1), (-1, idx + 1), colors.HexColor('#dcfce7'))]))
            
    elements.append(matrix_table)
    elements.append(Spacer(1, 15))

    # ── Section 2: Deep-Dive QCBS Matrix ──
    elements.append(Paragraph("Section 2: Deep-Dive QCBS (Quality-Cost Based Selection) Matrix", section_heading))
    
    qcbs_headers = [
        Paragraph("Vendor Entity", text_bold),
        Paragraph("Weighted Tech", text_bold),
        Paragraph("Weighted Fin", text_bold),
        Paragraph("ESG Score", text_bold),
        Paragraph("Supply Resilience", text_bold),
        Paragraph("Geo Risk", text_bold),
        Paragraph("QCBS Composite", text_bold)
    ]
    qcbs_data = [qcbs_headers]
    
    for q in dossier_data.get("qcbs_matrix", []):
        row = [
            Paragraph(f"<b>{q['vendor_name']}</b>", text_normal),
            Paragraph(f"{q['tech_weighted']}", text_normal),
            Paragraph(f"{q['fin_weighted']}", text_normal),
            Paragraph(f"{q['esg_score']}", text_normal),
            Paragraph(f"{q['supply_resilience']}%", text_normal),
            Paragraph(f"{q['geo_risk']}%", text_normal),
            Paragraph(f"<b>{q['qcbs_composite']}</b>", text_bold)
        ]
        qcbs_data.append(row)
        
    qcbs_table = Table(qcbs_data, colWidths=[1.8*inch, 0.9*inch, 0.9*inch, 0.7*inch, 1.1*inch, 0.7*inch, 1.1*inch])
    qcbs_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#334155')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#ffffff'))
    ]))
    # Highlight the first/highest composite row
    if len(dossier_data.get("qcbs_matrix", [])) > 0:
        qcbs_table.setStyle(TableStyle([('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#f0fdf4'))]))
        
    elements.append(qcbs_table)
    elements.append(Spacer(1, 15))

    # ── Section 3: Commercial & Technical PQC Audit Trail ──
    elements.append(Paragraph("Section 3: Pre-Qualification Criteria (PQC) Audit Trail", section_heading))
    
    pqc_vendors = (pqc_data or {}).get("vendors", [])
    if pqc_vendors:
        # Build a PQC audit trail table
        pqc_headers = [
            Paragraph("Vendor Name", text_bold),
            Paragraph("R1 (Exp)", text_bold),
            Paragraph("R2 (Turnover)", text_bold),
            Paragraph("R4 (MAF)", text_bold),
            Paragraph("R6 (Specs)", text_bold),
            Paragraph("Verdict Status", text_bold)
        ]
        pqc_table_data = [pqc_headers]
        
        for pv in pqc_vendors:
            r1 = "PASS"
            r2 = "PASS"
            r4 = "PASS"
            r6 = "PASS"
            
            for ev in pv.get("evaluations", []):
                rule_id = ev.get("rule", {}).get("id")
                status = ev.get("status")
                if status == "FAIL":
                    if rule_id == "R1": r1 = "FAIL"
                    elif rule_id == "R2": r2 = "FAIL"
                    elif rule_id == "R4": r4 = "FAIL"
                    elif rule_id == "R6": r6 = "FAIL"
            
            verdict = pv.get("status", "Pending")
            verdict_color = '#10b981' if verdict == 'Accepted' else ('#ef4444' if verdict == 'Rejected' else '#f59e0b')
            
            row = [
                Paragraph(f"<b>{pv['name']}</b>", text_normal),
                Paragraph(f"<font color='{'#10b981' if r1=='PASS' else '#ef4444'}'><b>{r1}</b></font>", text_normal),
                Paragraph(f"<font color='{'#10b981' if r2=='PASS' else '#ef4444'}'><b>{r2}</b></font>", text_normal),
                Paragraph(f"<font color='{'#10b981' if r4=='PASS' else '#ef4444'}'><b>{r4}</b></font>", text_normal),
                Paragraph(f"<font color='{'#10b981' if r6=='PASS' else '#ef4444'}'><b>{r6}</b></font>", text_normal),
                Paragraph(f"<font color='{verdict_color}'><b>{verdict}</b></font>", text_normal)
            ]
            pqc_table_data.append(row)
            
        pqc_table = Table(pqc_table_data, colWidths=[2.2*inch, 0.9*inch, 0.9*inch, 0.9*inch, 0.9*inch, 1.2*inch])
        pqc_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#ffffff'))
        ]))
        elements.append(pqc_table)
    else:
        elements.append(Paragraph("No bidder PQC data available in cache. Run a rescan on the dashboard first.", text_normal))
        
    elements.append(Spacer(1, 15))

    # ── Section 4: AI Threat Intelligence Alerts ──
    elements.append(Paragraph("Section 4: Threat Intelligence & pricing Anomaly Scan", section_heading))
    
    anomalies = dossier_data.get("anomalies", [])
    an_list = []
    for idx, a in enumerate(anomalies):
        sev = a.get("severity", "Risk")
        issue = a.get("issue", "")
        color = '#ef4444' if sev == 'Critical' else ('#f59e0b' if sev == 'High' else '#3b82f6')
        
        an_list.append([
            Paragraph(f"<font color='{color}'><b>[{sev.upper()} ALERT]</b></font>", text_bold),
            Paragraph(issue, text_normal)
        ])
        
    if an_list:
        an_table = Table(an_list, colWidths=[1.4*inch, 5.6*inch])
        an_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#fff5f5')),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LINEBELOW', (0,0), (-1,-2), 0.5, colors.HexColor('#fca5a5')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#ef4444'))
        ]))
        elements.append(an_table)
    else:
        elements.append(Paragraph("No severe anomalies or pricing collusion signals detected by Threat Sentinel.", text_normal))
        
    elements.append(Spacer(1, 15))

    # ── Section 5: Immutable Blockchain Audit Log ──
    elements.append(Paragraph("Section 5: Immutable Blockchain Lifecycle Audit Trail", section_heading))
    
    timeline = dossier_data.get("timeline", [])
    if timeline:
        timeline_data = [
            [Paragraph("Event Timestamp (UTC)", text_bold), Paragraph("Action Code", text_bold), Paragraph("Anti-Tamper Cryptographic Block Hash", text_bold)]
        ]
        for t in timeline:
            time_val = (t.get("time") or "N/A")[:19].replace("T", " ")
            action_val = t.get("action") or "N/A"
            hash_val = t.get("hash") or "N/A"
            row = [
                Paragraph(time_val, text_normal),
                Paragraph(action_val, text_normal),
                Paragraph(hash_val, code_style)
            ]
            timeline_data.append(row)
            
        timeline_table = Table(timeline_data, colWidths=[1.5*inch, 1.8*inch, 3.7*inch])
        timeline_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#020617')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#ffffff'))
        ]))
        elements.append(timeline_table)
    else:
        elements.append(Paragraph("No lifecycle events recorded for this tender.", text_normal))
        
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("<b>END OF DOSSIER REPORT</b><br/>This document is programmatically compiled and sealed under CVC standards.", ParagraphStyle('End', parent=text_normal, alignment=1, textColor=colors.HexColor('#64748b'))))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer

