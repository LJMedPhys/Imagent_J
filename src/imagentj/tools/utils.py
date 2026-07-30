import os
import re


def walk(dir_path: str, depth: int, max_depth: int = 5, recursive: bool = True, max_files_per_dir: int = 10) -> dict:
    node = {
        "name": os.path.basename(dir_path) or dir_path,
        "type": "directory",
        "children": []
    }
    if depth >= max_depth:
        return node
    try:
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        node["children"].append({
            "name": "<permission denied>",
            "type": "error"
        })
        return node

    files = []
    for entry in entries:
        full_path = os.path.join(dir_path, entry)
        if os.path.isdir(full_path):
            if recursive:
                node["children"].append(walk(full_path, depth + 1, max_depth, recursive, max_files_per_dir))
            else:
                node["children"].append({"name": entry, "type": "directory"})
        elif os.path.isfile(full_path):
            files.append(entry)

    # Add files with truncation
    visible_files = files[:max_files_per_dir]
    for f in visible_files:
        node["children"].append({"name": f, "type": "file"})

    hidden = len(files) - max_files_per_dir
    if hidden > 0:
        node["children"].append({"name": f"... and {hidden} more file(s)", "type": "truncated"})

    return node

def sanitize_filename(name: str) -> str:
    """Converts a script name into a valid filename."""
    # Remove invalid characters, replace spaces with underscores
    clean = re.sub(r'[<>:"/\\|?*]', '', name)
    return clean.replace(' ', '_')


# cat -n style: right-aligned line number, a TAB, then the line. The TAB is the
# delimiter _LINE_NUM_RE keys on when stripping, so a numbered read can be pasted
# straight back into edit_script without the prefix ever reaching the file.
def add_line_numbers(content: str) -> str:
    """Prefix every line with a 1-based line number (for display/reference only)."""
    lines = content.split('\n')
    width = max(6, len(str(len(lines))))
    return '\n'.join(f"{i:{width}d}\t{ln}" for i, ln in enumerate(lines, 1))


_LINE_NUM_RE = re.compile(r'^\s*\d+\t')


def strip_line_numbers(text: str) -> str:
    """Inverse of add_line_numbers, applied defensively to text a model may have copied
    from a numbered read. All-or-nothing: only strips when EVERY line carries a
    `<spaces><digits><TAB>` prefix (blank lines tolerated), so real source that merely
    starts with a digit is never touched. Returns text unchanged if it isn't numbered."""
    if not text:
        return text
    lines = text.split('\n')
    out = []
    for ln in lines:
        m = _LINE_NUM_RE.match(ln)
        if m:
            out.append(ln[m.end():])
        elif ln == '':
            out.append(ln)          # blank / trailing line — tolerate
        else:
            return text             # a non-numbered line ⇒ not a numbered block
    return '\n'.join(out)