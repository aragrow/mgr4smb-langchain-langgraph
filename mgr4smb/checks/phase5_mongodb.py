"""
Phase 5 sanity check — verify MongoDB knowledge base tool.

Usage:
    python -m mgr4smb.checks.phase5_mongodb
"""

import sys

from mgr4smb.logging_config import setup_logging

setup_logging(level="WARNING")

_results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"  {status} {label}"
    if not ok and detail:
        msg += f" — {detail}"
    print(msg)  # noqa: T201
    _results.append(ok)
    return ok


def main() -> int:
    print("Phase 5 — MongoDB Knowledge Base sanity check\n")  # noqa: T201

    # Import
    try:
        from mgr4smb.tools.mongodb_knowledge_base import mongodb_knowledge_base
        check("Import mongodb_knowledge_base", True)
    except Exception as e:
        check("Import mongodb_knowledge_base", False, str(e))
        return 1

    # @tool decorator
    has_tool = hasattr(mongodb_knowledge_base, "name") and hasattr(mongodb_knowledge_base, "description")
    check("mongodb_knowledge_base has @tool decorator", has_tool)

    # Signature
    import inspect
    inner = mongodb_knowledge_base.func if hasattr(mongodb_knowledge_base, "func") else mongodb_knowledge_base
    params = list(inspect.signature(inner).parameters.keys())
    check("Signature has search_query", "search_query" in params,
          f"got: {params}")

    # MongoDB connectivity + index
    try:
        from pymongo import MongoClient
        from mgr4smb.config import settings

        client = MongoClient(settings.mongodb_atlas_uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        check("MongoDB connection ping succeeds", True)

        db = client[settings.mongodb_db_name]
        collection_names = db.list_collection_names()
        check(
            f"Collection '{settings.mongodb_collection}' exists in '{settings.mongodb_db_name}'",
            settings.mongodb_collection in collection_names,
            f"found: {collection_names}",
        )

        # Verify the vector index exists
        col = db[settings.mongodb_collection]
        try:
            indexes = list(col.list_search_indexes())
            index_names = [i.get("name") for i in indexes]
            check(
                f"Vector index '{settings.mongodb_index_name}' exists",
                settings.mongodb_index_name in index_names,
                f"found search indexes: {index_names}",
            )
            # Active status
            for idx in indexes:
                if idx.get("name") == settings.mongodb_index_name:
                    status = idx.get("status", "unknown")
                    check(
                        f"Index '{settings.mongodb_index_name}' status is READY",
                        status.upper() == "READY",
                        f"status: {status}",
                    )
                    break
        except Exception as e:
            check("Vector index check", False, str(e))

    except Exception as e:
        check("MongoDB connection", False, str(e))

    # Vector search — live query
    try:
        result = mongodb_knowledge_base.invoke({"search_query": "What services do you offer?"})
        check(
            "Vector search returns a string",
            isinstance(result, str) and len(result) > 0,
            f"got: {type(result).__name__}",
        )
        # Length sanity: either a real match (>20 chars) or the "no info" fallback
        check(
            "Vector search returns non-trivial content",
            isinstance(result, str) and len(result) > 20,
            f"got {len(result) if isinstance(result, str) else 0} chars",
        )
    except Exception as e:
        check("Vector search runs without error", False, str(e))

    # Graceful no-match handling
    try:
        # A query that's unlikely to match anything in a cleaning-services KB
        result = mongodb_knowledge_base.invoke(
            {"search_query": "xyz completely unrelated quantum chromodynamics query 12345"}
        )
        # Either returns a (possibly weakly-matching) document OR the fallback
        check(
            "Unmatched query returns string (no raise)",
            isinstance(result, str) and len(result) > 0,
        )
    except Exception as e:
        check("Unmatched query handled gracefully", False, str(e))

    # Summary
    print()  # noqa: T201
    passed = sum(_results)
    total = len(_results)
    if all(_results):
        print(f"All {total} checks passed.")  # noqa: T201
    else:
        print(f"{passed}/{total} checks passed.")  # noqa: T201
    return 0 if all(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
