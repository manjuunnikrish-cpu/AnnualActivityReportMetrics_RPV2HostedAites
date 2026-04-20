"""
Annual Activity Report Metrics — Excel Data Query App
Accepts an Excel file upload and answers data questions via a web UI.
"""

import logging
import os
import re
import uuid

import numpy as np
import pandas as pd
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    session,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# SECRET_KEY must be set to a stable value in production to preserve sessions
# across restarts.  Falling back to os.urandom generates a new key on each
# restart, which is acceptable for development/demo use only.
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))


def _native(obj):
    """Recursively convert numpy/pandas scalars to native Python types."""
    if isinstance(obj, dict):
        return {k: _native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_native(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# In-memory store: session_id -> DataFrame
# Capped at MAX_SESSIONS entries; oldest entries are evicted when the limit is
# reached to prevent unbounded memory growth.
MAX_SESSIONS = 50
_data_store: dict[str, pd.DataFrame] = {}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def load_file(filepath: str) -> pd.DataFrame:
    """Load .xlsx, .xls, or .csv into a DataFrame."""
    ext = filepath.rsplit(".", 1)[1].lower()
    if ext == "csv":
        return pd.read_csv(filepath)
    return pd.read_excel(filepath)


def answer_question(df: pd.DataFrame, question: str) -> dict:
    """
    Parse a plain-English question and return an answer dict:
        { "answer": str, "table": list[dict] | None }
    """
    q = question.strip().lower()
    columns = list(df.columns)
    col_lower = {c.lower(): c for c in columns}

    # ── helper: find column name mentioned in the question ──────────────
    def find_col(text: str) -> str | None:
        for lc, orig in col_lower.items():
            if lc in text:
                return orig
        return None

    # ── helper: numeric columns ──────────────────────────────────────────
    num_cols = df.select_dtypes(include="number").columns.tolist()

    # ── how many rows / records ──────────────────────────────────────────
    if re.search(r"\b(how many|count|number of)\b.*(row|record|entr)", q):
        col = find_col(q)
        if col:
            cnt = df[col].count()
            return {"answer": f"There are {cnt:,} non-null values in '{col}'.", "table": None}
        return {"answer": f"There are {len(df):,} rows in the dataset.", "table": None}

    # ── columns / fields (checked before show so "show columns" lands here) ─
    if re.search(r"\bcolumns?\b|\bfields?\b|\bheaders?\b", q):
        return {
            "answer": f"The dataset has {len(columns)} column(s):",
            "table": [{"#": i + 1, "Column Name": c} for i, c in enumerate(columns)],
        }

    # ── summary / describe (checked before show) ─────────────────────────
    if re.search(r"summar\w*|describ\w*|\bstatistic|\boverview|\binfo\b", q):
        if num_cols:
            desc = df[num_cols].describe().round(2).reset_index()
            return {
                "answer": "Statistical summary of numeric columns:",
                "table": desc.to_dict(orient="records"),
            }
        return {"answer": "No numeric columns available for summary.", "table": None}

    # ── group by / breakdown (checked before total/sum) ──────────────────
    if re.search(r"\b(group|breakdown)\b|\bby\b.+\band\b|\bper\b|\beach\b", q):
        cols_found = [orig for lc, orig in col_lower.items() if lc in q]
        if len(cols_found) >= 2:
            grp_col, val_col = cols_found[0], cols_found[1]
            if val_col in num_cols:
                result = (
                    df.groupby(grp_col)[val_col]
                    .sum()
                    .reset_index()
                    .sort_values(val_col, ascending=False)
                )
                return {
                    "answer": f"Sum of '{val_col}' grouped by '{grp_col}':",
                    "table": result.round(2).to_dict(orient="records"),
                }
        return {"answer": "Please mention both a grouping column and a value column.", "table": None}

    # ── total / sum ──────────────────────────────────────────────────────
    if re.search(r"\b(total|sum)\b", q):
        col = find_col(q)
        if col and col in num_cols:
            val = df[col].sum()
            return {"answer": f"Total of '{col}': {val:,.2f}", "table": None}
        if num_cols:
            totals = {c: round(df[c].sum(), 2) for c in num_cols}
            return {
                "answer": "Totals for all numeric columns:",
                "table": [{"Column": k, "Total": v} for k, v in totals.items()],
            }
        return {"answer": "No numeric columns found.", "table": None}

    # ── average / mean ───────────────────────────────────────────────────
    if re.search(r"\b(average|avg|mean)\b", q):
        col = find_col(q)
        if col and col in num_cols:
            val = df[col].mean()
            return {"answer": f"Average of '{col}': {val:,.2f}", "table": None}
        if num_cols:
            avgs = {c: round(df[c].mean(), 2) for c in num_cols}
            return {
                "answer": "Averages for all numeric columns:",
                "table": [{"Column": k, "Average": v} for k, v in avgs.items()],
            }
        return {"answer": "No numeric columns found.", "table": None}

    # ── maximum ──────────────────────────────────────────────────────────
    if re.search(r"\b(max|maximum|highest|largest|top)\b", q):
        col = find_col(q)
        if col and col in num_cols:
            val = df[col].max()
            idx = df[col].idxmax()
            row = df.loc[idx].to_dict()
            return {
                "answer": f"Maximum value of '{col}': {val:,.2f} (row {idx})",
                "table": [{k: str(v) for k, v in row.items()}],
            }
        if num_cols:
            maxes = {c: round(df[c].max(), 2) for c in num_cols}
            return {
                "answer": "Maximum values for all numeric columns:",
                "table": [{"Column": k, "Max": v} for k, v in maxes.items()],
            }
        return {"answer": "No numeric columns found.", "table": None}

    # ── minimum ──────────────────────────────────────────────────────────
    if re.search(r"\b(min|minimum|lowest|smallest)\b", q):
        col = find_col(q)
        if col and col in num_cols:
            val = df[col].min()
            idx = df[col].idxmin()
            row = df.loc[idx].to_dict()
            return {
                "answer": f"Minimum value of '{col}': {val:,.2f} (row {idx})",
                "table": [{k: str(v) for k, v in row.items()}],
            }
        if num_cols:
            mins = {c: round(df[c].min(), 2) for c in num_cols}
            return {
                "answer": "Minimum values for all numeric columns:",
                "table": [{"Column": k, "Min": v} for k, v in mins.items()],
            }
        return {"answer": "No numeric columns found.", "table": None}

    # ── unique values ────────────────────────────────────────────────────
    if re.search(r"\b(unique|distinct|different)\b", q):
        col = find_col(q)
        if col:
            vals = df[col].dropna().unique().tolist()
            vals_str = [str(v) for v in vals[:100]]
            return {
                "answer": f"{len(vals)} unique value(s) in '{col}':",
                "table": [{"Value": v} for v in vals_str],
            }
        return {"answer": "Please mention a column name to find unique values.", "table": None}

    # ── show / display / preview ─────────────────────────────────────────
    if re.search(r"\b(show|display|preview|first|top|head)\b", q):
        numbers = re.findall(r"\d+", q)
        n = int(numbers[0]) if numbers else 10
        n = min(n, 100)
        preview = df.head(n).fillna("").astype(str)
        return {
            "answer": f"Showing first {n} row(s):",
            "table": preview.to_dict(orient="records"),
        }

    # ── sort ─────────────────────────────────────────────────────────────
    if re.search(r"\b(sort|order|rank)\b", q):
        col = find_col(q)
        ascending = not re.search(r"\b(desc|descend|descending|high|large)\b", q)
        if col:
            sorted_df = df.sort_values(col, ascending=ascending).head(50).fillna("").astype(str)
            direction = "ascending" if ascending else "descending"
            return {
                "answer": f"Data sorted by '{col}' ({direction}), showing top 50:",
                "table": sorted_df.to_dict(orient="records"),
            }
        return {"answer": "Please mention a column name to sort by.", "table": None}

    # ── filter / where ───────────────────────────────────────────────────
    if re.search(r"\b(filter|where|with|having)\b", q):
        col = find_col(q)
        if col:
            # Try to extract value after "is", "=", "equals", etc.
            match = re.search(
                r"(?:is|=|equals?|:)\s*['\"]?([^\s'\"]+)['\"]?", q
            )
            if match:
                val_str = match.group(1)
                if col in num_cols:
                    try:
                        val = float(val_str)
                        filtered = df[df[col] == val]
                    except ValueError:
                        filtered = df
                else:
                    filtered = df[df[col].astype(str).str.lower() == val_str.lower()]
                filtered = filtered.fillna("").astype(str)
                return {
                    "answer": f"Found {len(filtered):,} row(s) where '{col}' is '{val_str}':",
                    "table": filtered.head(100).to_dict(orient="records"),
                }
        return {"answer": "Please mention a column name and a value to filter by.", "table": None}

    # ── default: show columns and row count ─────────────────────────────
    return {
        "answer": (
            f"Dataset has {len(df):,} rows and {len(columns)} columns: "
            + ", ".join(f"'{c}'" for c in columns)
            + ". Try asking for totals, averages, unique values, summaries, or filtered data."
        ),
        "table": None,
    }


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part in request."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Unsupported file type. Please upload .xlsx, .xls, or .csv."}), 400

    # Map the validated extension to a safe, fixed extension string so that
    # no user-controlled data is included in the on-disk file path.
    raw_ext = file.filename.rsplit(".", 1)[1].lower()
    safe_ext_map = {"xlsx": "xlsx", "xls": "xls", "csv": "csv"}
    safe_ext = safe_ext_map.get(raw_ext, "tmp")
    unique_name = f"{uuid.uuid4().hex}.{safe_ext}"
    filepath = os.path.join(UPLOAD_FOLDER, unique_name)
    file.save(filepath)

    try:
        df = load_file(filepath)
    except Exception as exc:
        logger.warning("Failed to parse uploaded file: %s", exc)
        return jsonify({"error": "Could not read file. Please ensure it is a valid Excel or CSV file."}), 422
    finally:
        # Always remove the temporary file from disk — DataFrame is kept in memory.
        try:
            os.remove(filepath)
        except OSError:
            pass

    # Assign a session key and store DataFrame
    sid = session.get("sid") or uuid.uuid4().hex
    session["sid"] = sid
    # Evict oldest entry if we are at the cap
    if len(_data_store) >= MAX_SESSIONS and sid not in _data_store:
        oldest = next(iter(_data_store))
        del _data_store[oldest]
    _data_store[sid] = df

    preview = df.head(10).fillna("").astype(str).to_dict(orient="records")
    return jsonify(
        {
            "rows": len(df),
            "columns": list(df.columns),
            "preview": preview,
        }
    )


@app.route("/ask", methods=["POST"])
def ask():
    sid = session.get("sid")
    if not sid or sid not in _data_store:
        return jsonify({"error": "No dataset loaded. Please upload an Excel file first."}), 400

    body = request.get_json(silent=True) or {}
    question = body.get("question", "").strip()
    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    df = _data_store[sid]
    result = answer_question(df, question)
    return jsonify(_native(result))


if __name__ == "__main__":
    app.run(debug=False, port=5000)
