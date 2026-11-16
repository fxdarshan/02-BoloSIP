"""Render a Markdown doc as plain text (used for Doc/problem_statement.txt).

Usage: python scripts/md_to_txt.py Doc/problem_statement.md Doc/problem_statement.txt
"""
import re
import sys


def convert(md: str) -> str:
    out, header = [], None
    for line in md.splitlines():
        s = line.rstrip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r"-+", c) for c in cells):
                continue
            if header is None:
                header = cells
                continue
            out.append("- " + " | ".join(cells))
            continue
        header = None
        if s == "---":
            out.append("")
            continue
        m = re.match(r"(#+) (.*)", s)
        if m:
            title, level = m.group(2), len(m.group(1))
            out.append(title.upper() if level == 1 else title)
            out.append(("=" if level <= 2 else "-") * len(title))
            continue
        s = re.sub(r"^>$", "", s)
        s = re.sub(r"^> ?", "    ", s)
        out.append(s)
    txt = "\n".join(out).replace("**", "").replace("`", "")
    txt = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", txt)
    txt = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", txt)
    return re.sub(r"\n{3,}", "\n\n", txt).strip() + "\n"


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        text = convert(f.read())
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {dst}")
