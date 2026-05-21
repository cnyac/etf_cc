"""
parse_annotation.py — 从用户批注过的 docx 报告里提取备注列数据。

逻辑：
  - 打开 docx，遍历所有表格
  - 找到含「备注」列标题的表格（即本项目渲染的报告表格）
  - 提取每行的「代码」列 + 「备注」列文本
  - 备注文本约定格式：「颜色名 [其余批注文字]」
      e.g. "红色 突破缺口注意"  → color_name="红色",  note_text="突破缺口注意"
           "夕阳红-关注"        → color_name="夕阳红", note_text="关注"（以连字符拆分）
           "突破缺口注意"       → color_name="",       note_text="突破缺口注意"
  - 第一个空白分隔的词视为颜色名，其余视为批注；
    颜色名 → RGB 的映射工作交由 Claude Code 在合并分析阶段完成。

返回值：dict[code, {"color_name": str, "note_text": str}]
"""
from __future__ import annotations

import re
from pathlib import Path


def _split_note(cell_text: str) -> dict:
    """把备注单元格文本拆成 {color_name, note_text}。

    约定：第一个空白 / 连字符 / 顿号前的词为颜色名；
    若该词含「色」字或已知颜色关键字则优先提取；
    其余均视为批注正文。
    Claude 会在合并阶段判断 color_name 是否确实是颜色。
    """
    text = cell_text.strip()
    if not text:
        return {"color_name": "", "note_text": ""}
    # 以第一个空白、-、、或 | 作为分隔符
    m = re.match(r"^(\S+?)[\s\-、|]+(.*)", text, re.DOTALL)
    if m:
        return {"color_name": m.group(1), "note_text": m.group(2).strip()}
    # 没有分隔符：整个文本是颜色名（如用户只写了"红色"）
    return {"color_name": text, "note_text": ""}


def extract_annotations(docx_path: str | Path) -> dict[str, dict]:
    """从 docx 中提取所有备注列批注，按 code 索引。

    返回：
        {
            "510300": {"color_name": "红色",  "note_text": "突破缺口"},
            "513050": {"color_name": "夕阳红", "note_text": "量能存疑"},
            ...
        }

    若 docx 没有包含「代码」和「备注」列的表格，返回空 dict。
    """
    from docx import Document  # 延迟导入，避免非 docx 场景的开销

    doc = Document(str(docx_path))
    result: dict[str, dict] = {}

    for table in doc.tables:
        if not table.rows:
            continue
        # 取表头行
        header_cells = [c.text.strip() for c in table.rows[0].cells]

        # 找「代码」和「备注」列的索引
        try:
            idx_code = header_cells.index("代码")
            idx_note = header_cells.index("备注")
        except ValueError:
            continue  # 这张表没有目标列，跳过

        # 遍历数据行
        for row in table.rows[1:]:
            cells = row.cells
            if len(cells) <= max(idx_code, idx_note):
                continue
            code      = cells[idx_code].text.strip()
            note_raw  = cells[idx_note].text.strip()
            if not code or not note_raw:
                continue
            result[code] = _split_note(note_raw)

    return result


if __name__ == "__main__":
    import json, sys
    if len(sys.argv) < 2:
        print("用法: python parse_annotation.py <report.docx>")
        sys.exit(1)
    ann = extract_annotations(sys.argv[1])
    print(json.dumps(ann, ensure_ascii=False, indent=2))
    print(f"\n共解析到 {len(ann)} 条批注")
