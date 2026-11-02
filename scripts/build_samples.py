"""Rebuild the 16 fictional fixtures; no customer information is included."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from matterloom.parsing import render_page

NOTICE = "模拟材料，仅用于产品测试。所有主体、交易及记录均为虚构。"
CASES = [
    {"key": "purchase", "name": "设备买卖款项核对", "description": "围绕交付、两笔付款及质量争议，核对材料中不同的金额。", "files": [
        {"id": "A01", "title": "设备买卖合同", "format": "pdf", "pages": [
            ["合同编号：模拟 ML-A-2026-001", "签署日期：2026年10月1日", "卖方：模拟甲辰设备公司（以下简称甲方）。买方：模拟乙川商贸公司（以下简称乙方）。",
             "一 采购标的", "乙方向甲方采购通用设备100件，每件单价人民币1,000元，合同总价人民币100,000元。设备型号为模拟设备 ML-100。",
             "二 交付安排", "甲方计划于2026年10月8日送达乙方指定测试收货地点。收货联系人为周衡。实际交付数量及日期以双方后续签收材料记载为准。"],
            ["三 付款安排", "乙方于2026年10月10日前支付人民币40,000元，剩余价款于2026年10月20日前支付。付款账户在本模拟样本中省略。",
             "四 质量问题处理", "买方提出质量异议后，双方另行核实问题范围及处理方案。任何退货、换货或价款调整以双方进一步确认的记录为依据。",
             "五 文件说明", "本合同仅用于测试信息提取、金额核对和原文定位，不作为真实合同使用。", "甲方代表：陈砚（模拟）；乙方代表：周衡（模拟）。"]]},
        {"id": "A02", "title": "采购确认单", "format": "docx", "paragraphs": ["发送方：模拟乙川商贸公司；接收方：模拟甲辰设备公司。", "确认日期：2026年10月3日。", "本确认单中的“乙川商贸”指模拟乙川商贸公司。“甲辰设备”指模拟甲辰设备公司。", "请按下表准备设备，送货前联系周衡。"], "table": [["项目", "确认内容"], ["设备型号", "模拟设备 ML-100"], ["数量", "100件"], ["收货联系人", "周衡"], ["计划收货日期", "2026年10月8日"]], "after": ["数量和型号对应合同 ML-A-2026-001；本单不变更合同总价。"]},
        {"id": "A03", "title": "送货签收单", "format": "scan", "pages": [["送货编号：模拟 DELIVERY-A03", "送货单位：模拟甲辰设备公司。收货单位：模拟乙川商贸公司。", "实际签收日期：2026年10月8日。", "设备型号：模拟设备 ML-100。送达数量：100件。", "收货联系人：周衡。", "备注：仅确认当日收到上述数量设备，设备功能另行检查。", "签收记载：周衡（模拟打印姓名，无真实签名）。"]]},
        {"id": "A04", "title": "质量问题沟通记录", "format": "pdf", "pages": [["记录范围：2026年10月12日至10月13日的模拟邮件往来。", "2026年10月12日，周衡代表买方提出：其中10件设备运行不稳定，希望减少价款人民币10,000元。", "2026年10月13日，陈砚代表卖方回复：请先提供问题视频及设备编号，我们核实后再讨论处理方式，目前无法确认减价。", "本记录不包含后续达成一致的邮件，也未附退货单。"]]},
        {"id": "A05", "title": "阶段对账单", "format": "docx", "paragraphs": ["编制方：模拟甲辰设备公司。对账截止日期：2026年10月21日。", "对应事项：模拟乙川商贸公司采购100件设备。"], "table": [["项目", "金额", "依据"], ["合同总价", "100,000元", "ML-A-2026-001"], ["已登记付款", "40,000元", "2026年10月10日付款"], ["账面差额", "60,000元", "本表编制时的余额"]], "after": ["本表由卖方单方编制。买方确认栏：空白。", "质量争议尚在沟通，本表未计入任何减价调整。"]},
        {"id": "A06", "title": "两笔付款回单汇总", "format": "pdf", "pages": [
            ["模拟转账记录一", "流水编号：TEST-PAY-A061", "付款日期：2026年10月10日", "付款方：模拟乙川商贸公司", "收款方：模拟甲辰设备公司", "付款金额：人民币40,000元", "用途：设备价款第一笔付款。", "本页仅为测试回单，不对应任何真实银行或账户。"],
            ["模拟转账记录二", "流水编号：TEST-PAY-A062", "付款日期：2026年10月22日", "付款方：模拟乙川商贸公司", "收款方：模拟甲辰设备公司", "付款金额：人民币20,000元", "用途：设备价款追加付款。", "本页仅为测试回单，不对应任何真实银行或账户。"]]},
        {"id": "A07", "title": "催款函", "format": "pdf", "pages": [["发函方：模拟甲辰设备公司。收函方：模拟乙川商贸公司。", "发函日期：2026年10月23日。", "根据我方2026年10月21日编制的对账单，贵方尚有设备价款人民币60,000元未付，现请核对并安排付款。", "如已付款，请提供对应凭证，以便更新账目。", "本函未另附发函日的账户核对结果。"]]},
        {"id": "A08", "title": "电话沟通纪要", "format": "docx", "paragraphs": ["记录日期：2026年10月24日。记录人：陈砚（模拟）。", "参与人：陈砚、周衡。", "周衡表示已在10月22日追加支付20,000元，请卖方查收。", "关于10件设备的质量问题，周衡继续要求减少价款10,000元。陈砚表示尚需核验，不确认减价。", "双方约定继续补充设备编号和问题记录。", "本纪要未记载已经退货，也未记载双方最终接受减价。"]}
    ]},
    {"key": "employment", "name": "离职工资与交接核对", "description": "分清工资标准、实际到账和离职相关日期，保留待核实的信息。", "files": [
        {"id": "B01", "title": "劳动合同", "format": "pdf", "pages": [
            ["合同编号：模拟 ML-B-2026-001", "用人单位：模拟青禾信息公司。劳动者：林澄（模拟人物）。", "签署日期：2026年6月25日。入职日期：2026年7月1日。", "一 工作岗位", "岗位为项目助理，工作安排由模拟项目组负责。", "二 工资标准", "合同记载月工资标准为人民币8,000元。工资支付及具体扣减以相关制度、月度核算和实际记录核对。"],
            ["三 工作记录", "考勤和外出安排由主管登记，劳动者可以提交补充说明。", "四 交接", "离职相关安排由双方进一步沟通，交接时形成书面记录。", "五 样本用途", "本合同不含真实身份信息，仅用于测试主体、日期、金额及不同来源的关联。"]]},
        {"id": "B02", "title": "录用通知", "format": "docx", "paragraphs": ["致：林澄。发出方：模拟青禾信息公司。", "通知日期：2026年6月20日。", "本通知确认以下拟录用安排，后续以双方签署文件和实际履行记录核对。"], "table": [["项目", "内容"], ["岗位", "项目助理"], ["月工资标准", "8,000元"], ["报到日期", "2026年7月1日"], ["所属团队", "模拟项目组"]]},
        {"id": "B03", "title": "月度考勤表", "format": "pdf", "pages": [["员工：林澄；单位：模拟青禾信息公司。", "考勤月份：2026年9月。导出日期：2026年10月2日。", "表格摘要如下。主管后续补充说明未在本次导出记录中体现。"]], "table": [["日期", "考勤状态", "备注"], ["2026年9月14日", "正常出勤", "测试记录"], ["2026年9月15日", "缺勤", "未登记外出"], ["2026年9月16日", "正常出勤", "测试记录"]]},
        {"id": "B04", "title": "工资明细表", "format": "pdf", "pages": [["员工：林澄；发薪单位：模拟青禾信息公司。", "工资月份：2026年9月。制表日期：2026年10月5日。"]], "table": [["项目", "金额", "说明"], ["合同月工资标准", "8,000元", "供对照"], ["本月应发", "7,600元", "具体核算依据未附"], ["本月扣减", "700元", "明细未附"], ["本月实发", "6,900元", "7,600减700"]]},
        {"id": "B05", "title": "工资到账记录", "format": "pdf", "pages": [["流水编号：TEST-SALARY-B05。", "到账日期：2026年10月8日。", "付款方：模拟青禾信息公司。收款方：林澄。", "到账金额：人民币6,900元。", "附言：2026年9月工资。", "本记录为虚构到账记录，不包含真实银行名称或账号。"]]},
        {"id": "B06", "title": "离职通知", "format": "docx", "paragraphs": ["发出人：林澄。接收方：模拟青禾信息公司人事部门。", "通知日期：2026年10月1日。", "本人希望于2026年10月15日离职，请安排相关工作交接，并核对2026年9月工资明细。", "本人对考勤中2026年9月15日的缺勤记录有疑问，希望补充核实。", "本文件仅记载劳动者提出的安排，不包含单位回复或双方最终确认。"]},
        {"id": "B07", "title": "人事及主管沟通记录", "format": "pdf", "pages": [["2026年10月3日，人事回复林澄：建议于10月18日办理工作交接，具体安排请与主管确认。", "2026年10月6日，主管回复：9月15日林澄可能在外出处理项目事项，我需要核对当日工作记录后再确认。", "2026年10月7日，林澄回复：请补充9月工资应发及扣减的明细。", "本汇总未包含进一步确认终止日期的记录，未附主管最终考勤修订及工资计算明细。"]]},
        {"id": "B08", "title": "工作交接确认单", "format": "scan", "pages": [["单位：模拟青禾信息公司。交接人：林澄。", "实际交接日期：2026年10月18日。", "接收人：顾遥（模拟）。", "交接内容：项目清单、工作文件目录及模拟设备。", "备注：本单确认上述交接动作完成。工资核对另行处理。", "本单未填写劳动关系终止日期。", "交接人和接收人姓名仅为模拟打印记载。"]]}
    ]}
]


def make_pdf(path, item):
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    normal = ParagraphStyle("cn", fontName="STSong-Light", fontSize=12, leading=21, spaceAfter=12)
    title = ParagraphStyle("title", parent=normal, fontSize=22, leading=29, spaceAfter=20)
    small = ParagraphStyle("small", parent=normal, fontSize=9, leading=15, textColor=colors.HexColor("#7b8076"), spaceAfter=18)
    flow = []
    for index, lines in enumerate(item["pages"]):
        if index: flow.append(PageBreak())
        flow.extend([Paragraph(item["title"] + (" 续页" if index else ""), title), Paragraph(NOTICE, small)])
        for text in lines:
            flow.append(Paragraph(text, normal))
        if item.get("table") and index == 0:
            rows = [[Paragraph(str(c), normal) for c in row] for row in item["table"]]
            table = Table(rows, colWidths=[150] * len(rows[0]), repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#eef1eb")), ("GRID",(0,0),(-1,-1),.5,colors.HexColor("#d1d8cc")),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
            flow.extend([Spacer(1,8),table])
    def footer(c, doc):
        c.setFont("STSong-Light", 9); c.setFillColor(colors.HexColor("#878c80"))
        c.drawString(56, 35, "MatterLoom 模拟案卷 / " + item["id"])
        c.drawRightString(556, 35, f"{doc.page}")
    SimpleDocTemplate(str(path), pagesize=(612,792), leftMargin=56,rightMargin=56,topMargin=52,bottomMargin=55, title=item["title"], author="MatterLoom fictional fixtures").build(flow,onFirstPage=footer,onLaterPages=footer)


def make_docx(path, item):
    document = Document()
    # Clear decorative defaults from the runtime's base document template.
    for root in [document.element, document.styles.element]:
        for border in root.xpath('.//w:pBdr'):
            border.getparent().remove(border)
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(.75)
    section.left_margin = section.right_margin = Inches(.8)
    for name in ["Normal", "Title", "Heading 1"]:
        style = document.styles[name]
        style.font.name = "Songti SC"
        font = style.element.get_or_add_rPr().rFonts
        for attribute in list(font.attrib):
            if "Theme" in attribute or "theme" in attribute:
                del font.attrib[attribute]
        font.set(qn("w:eastAsia"), "Songti SC")
        style.font.size = Pt(12 if name == "Normal" else 23 if name == "Title" else 16)
        style.font.color.rgb = RGBColor.from_string("000000" if name == "Title" else "202B25")
        style.paragraph_format.space_after = Pt(11)
        style.paragraph_format.line_spacing = 1.35
    document.add_paragraph(item["title"], "Title")
    document.add_paragraph(NOTICE)
    for line in item["paragraphs"]:
        document.add_paragraph(line)
    if item.get("table"):
        table = document.add_table(rows=0, cols=len(item["table"][0]))
        table.style = "Table Grid"
        borders = OxmlElement('w:tblBorders')
        for edge in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
            line = OxmlElement('w:' + edge)
            for attr, value in [('val', 'single'), ('sz', '4'), ('color', 'D9D9D9')]:
                line.set(qn('w:' + attr), value)
            borders.append(line)
        table._tbl.tblPr.append(borders)
        for row in item["table"]:
            cells = table.add_row().cells
            for cell, text in zip(cells, row):
                cell.text = text
                for p in cell.paragraphs:
                    p.paragraph_format.space_before = Pt(5)
                    p.paragraph_format.space_after = Pt(5)
        for cell in table.rows[0].cells:
            shading = OxmlElement('w:shd'); shading.set(qn('w:fill'), 'EEF1EB')
            cell._tc.get_or_add_tcPr().append(shading)
            for run in cell.paragraphs[0].runs:
                run.bold = True
    for line in item.get("after", []):
        paragraph = document.add_paragraph(line)
        paragraph.paragraph_format.space_before = Pt(10)
    document.core_properties.author = "MatterLoom"
    document.core_properties.title = item["title"]
    document.save(path)


def main():
    output = ROOT / "samples"
    qa = ROOT / "work/sample-qa"
    qa.mkdir(parents=True, exist_ok=True)
    manifest = {"fictional": True, "notice": NOTICE, "matters": []}
    for case in CASES:
        folder = output / case["key"]
        folder.mkdir(parents=True, exist_ok=True)
        row = {k: case[k] for k in ("key", "name", "description")}
        row["files"] = []
        for item in case["files"]:
            extension = "docx" if item["format"] == "docx" else "pdf"
            name = item["id"] + "_" + item["title"] + "." + extension
            path = folder / name
            if extension == "docx":
                make_docx(path, item)
            elif item["format"] == "scan":
                clean = qa / (item["id"] + "-text.pdf")
                make_pdf(clean, item)
                png = render_page(clean, 1, 2)
                scanned = canvas.Canvas(str(path), pagesize=(612,792))
                scanned.setTitle(item["title"] + " 模拟扫描件")
                scanned.drawImage(ImageReader(io.BytesIO(png)), 0, 0, width=612, height=792)
                scanned.showPage(); scanned.save()
            else:
                make_pdf(path, item)
            row["files"].append({"id": item["id"], "name": name, "format": item["format"]})
        manifest["matters"].append(row)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Created 16 fictional files: 11 PDFs (2 image-only scans) and 5 DOCX files.")


if __name__ == "__main__":
    main()
