#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把已排版的「工作汇报」docx 就地调整为扬州港集团公文格式。

为什么不直接用 skill 的 beautify_report.py：
  该脚本 new Document() 后只遍历 src.paragraphs 复制文字，
  - 会丢弃全部表格（本文件有 9 张数据表）
  - 会给已带「一、」的标题再加一次序号，变成「一、一、」
  - 封面与目录会被当成正文，加首行缩进
因此本脚本基于同一套 common.py 规范常量，改为**在原文档上就地套格式**，
保留分节、目录域、页码域、表格结构与底纹。

规范来源：scripts/common.py（对齐《办法》附件3《公文格式》）
  A4；边距 上37/下35/左28/右26 mm；行距固定 28.9 磅
  标题 2号方正小标宋；一级(章) 3号方正黑体；二级(节) 3号方正楷体
  正文 3号方正仿宋、首行缩进2字符、两端对齐
  页码 4号 TNR「— N —」、奇偶页不同（奇右偶左各空一字）、页脚距 17.5 mm
  页眉默认不加
"""
import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt, Cm, Mm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/Users/tristan/.workbuddy/skills/公司公文处理/scripts")
from common import (  # noqa: E402
    FONT_FANGSONG, FONT_KAITI, FONT_HEITI, FONT_XIAOBIAOSONG, FONT_TIMES,
    TITLE_SIZE, BODY_SIZE, HEADER_FOOTER_SIZE, LINE_SPACING_PT, INDENT_CM,
    set_run_font, set_line_spacing, setup_page, add_page_number_footer,
)

FOOTER_MM = 17.5          # 本项目范文值，覆盖《办法》28mm
TABLE_SIZE = Pt(12)       # 表内文字小四（三号在 5 列表格中过挤）
TABLE_HDR_SIZE = Pt(12)


def clear_paragraph(p):
    """清空段落内所有 run，保留段落属性。"""
    for child in list(p._p):
        if child.tag == qn("w:r"):
            p._p.remove(child)


def fmt_para(p, font, size, align, indent=True, bold=False,
             sb=0, sa=0, line=LINE_SPACING_PT):
    set_line_spacing(p, line)
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(sb)
    pf.space_after = Pt(sa)
    pf.first_line_indent = Cm(INDENT_CM) if indent else None
    for r in p.runs:
        set_run_font(r, font, size, bold=bold)


def main(src, dst, header=False):
    doc = Document(src)

    # ---------- 1. 页面设置（所有分节） ----------
    for sec in doc.sections:
        setup_page(sec, footer_distance_mm=FOOTER_MM)

    # ---------- 2. 定位分区：封面 / 目录 / 正文 ----------
    paras = doc.paragraphs
    toc_idx = body_idx = None
    for i, p in enumerate(paras):
        t = p.text.strip().replace("　", "")
        if toc_idx is None and t == "目录":
            toc_idx = i
        if toc_idx is not None and body_idx is None and p.style.name.startswith("Heading"):
            body_idx = i
            break
    if body_idx is None:
        body_idx = len(paras)
    if toc_idx is None:
        toc_idx = 0

    print(f"  结构定位：封面 0..{toc_idx - 1}，目录 {toc_idx}..{body_idx - 1}，正文 {body_idx}..{len(paras) - 1}")

    # ---------- 3. 逐段套格式 ----------
    stat = {"cover": 0, "toc": 0, "h2": 0, "h3": 0, "body": 0}
    for i, p in enumerate(paras):
        txt = p.text.strip()
        if not txt:
            continue
        style = p.style.name

        # --- 封面区 ---
        if i < toc_idx:
            if "建设进度汇报" in txt or "职工特色菜订餐系统" in txt:
                # 主标题：2号方正小标宋，居中
                fmt_para(p, FONT_XIAOBIAOSONG, TITLE_SIZE,
                         WD_ALIGN_PARAGRAPH.CENTER, indent=False)
                stat["cover"] += 1
            elif "从需求调研到" in txt:
                # 副标题：3号楷体，居中
                fmt_para(p, FONT_KAITI, BODY_SIZE,
                         WD_ALIGN_PARAGRAPH.CENTER, indent=False)
                stat["cover"] += 1
            elif txt.startswith("江") and "港" in txt:
                # 眉标：3号黑体，居中
                fmt_para(p, FONT_HEITI, BODY_SIZE,
                         WD_ALIGN_PARAGRAPH.CENTER, indent=False)
                stat["cover"] += 1
            else:
                # 汇报单位 / 时间：3号仿宋，居中
                fmt_para(p, FONT_FANGSONG, BODY_SIZE,
                         WD_ALIGN_PARAGRAPH.CENTER, indent=False)
                stat["cover"] += 1
            continue

        # --- 目录区 ---
        if i < body_idx:
            if txt.replace("　", "") == "目录":
                fmt_para(p, FONT_HEITI, BODY_SIZE,
                         WD_ALIGN_PARAGRAPH.CENTER, indent=False,
                         sb=0, sa=LINE_SPACING_PT * 0.5)
            else:
                fmt_para(p, FONT_FANGSONG, BODY_SIZE,
                         WD_ALIGN_PARAGRAPH.LEFT, indent=False, line=24)
            stat["toc"] += 1
            continue

        # --- 正文区 ---
        if style == "Heading 2":
            # 一级（章）：3号方正黑体，已有「一、」序号，不再追加
            fmt_para(p, FONT_HEITI, BODY_SIZE, WD_ALIGN_PARAGRAPH.LEFT,
                     indent=True, bold=False,
                     sb=LINE_SPACING_PT * 0.5, sa=LINE_SPACING_PT * 0.2)
            stat["h2"] += 1
        elif style == "Heading 3":
            # 二级（节）：3号方正楷体，已有「2.1」编号，不再追加
            fmt_para(p, FONT_KAITI, BODY_SIZE, WD_ALIGN_PARAGRAPH.LEFT,
                     indent=True, bold=False,
                     sb=LINE_SPACING_PT * 0.3, sa=LINE_SPACING_PT * 0.1)
            stat["h3"] += 1
        elif style == "Heading 1":
            fmt_para(p, FONT_XIAOBIAOSONG, TITLE_SIZE,
                     WD_ALIGN_PARAGRAPH.CENTER, indent=False)
        else:
            # 正文：3号方正仿宋、首行缩进2字符、两端对齐
            # 保留源文档已有的选择性加粗（不整段加粗）
            fmt_para(p, FONT_FANGSONG, BODY_SIZE, WD_ALIGN_PARAGRAPH.JUSTIFY,
                     indent=True, bold=None)
            stat["body"] += 1

    print("  段落处理：封面 %(cover)d / 目录 %(toc)d / 章 %(h2)d / 节 %(h3)d / 正文 %(body)d" % stat)

    # ---------- 4. 表格：仿宋小四，表头黑体，保留底纹 ----------
    tn = 0
    for tbl in doc.tables:
        tn += 1
        for ri, row in enumerate(tbl.rows):
            for cell in row.cells:
                for p in cell.paragraphs:
                    set_line_spacing(p, 16)
                    p.alignment = (WD_ALIGN_PARAGRAPH.CENTER if ri == 0
                                   else WD_ALIGN_PARAGRAPH.LEFT)
                    p.paragraph_format.first_line_indent = None
                    p.paragraph_format.space_before = Pt(2)
                    p.paragraph_format.space_after = Pt(2)
                    for r in p.runs:
                        if ri == 0:
                            set_run_font(r, FONT_HEITI, TABLE_HDR_SIZE, bold=False)
                        else:
                            set_run_font(r, FONT_FANGSONG, TABLE_SIZE, bold=None)
    print(f"  表格处理：{tn} 张")

    # ---------- 5. 页码：仅正文节显示，— N —，奇偶页不同 ----------
    for idx, sec in enumerate(doc.sections):
        sec.footer.is_linked_to_previous = False
        sec.even_page_footer.is_linked_to_previous = False
        # 先清空既有页脚（转换时已生成过 PAGE 域，避免重复）
        for fp in list(sec.footer.paragraphs):
            clear_paragraph(fp)
        for fp in list(sec.even_page_footer.paragraphs):
            clear_paragraph(fp)

        is_last = (idx == len(doc.sections) - 1)
        if is_last:
            add_page_number_footer(sec, doc)
            # 正文页码从 1 重起
            sectPr = sec._sectPr
            for old in sectPr.findall(qn("w:pgNumType")):
                sectPr.remove(old)
            pg = OxmlElement("w:pgNumType")
            pg.set(qn("w:start"), "1")
            sectPr.append(pg)

    # ---------- 6. 页眉：默认不加 ----------
    if header:
        for sec in doc.sections:
            hp = sec.header.paragraphs[0]
            hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = hp.add_run("内部资料　注意保管")
            set_run_font(r, FONT_FANGSONG, HEADER_FOOTER_SIZE)

    doc.save(dst)
    print(f"  已保存：{dst}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python apply_gongwen_format.py <输入.docx> <输出.docx> [--header]")
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2], header="--header" in sys.argv)
