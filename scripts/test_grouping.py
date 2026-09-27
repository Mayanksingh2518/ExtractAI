"""Checks for app/services/grouping.py. No Ollama needed.

Usage:  python -m scripts.test_grouping
"""

from app.schemas.classification import Classification, DocumentType
from app.services.grouping import group_by_owner

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")


def doc(name: str | None, doc_type: DocumentType = DocumentType.PASSPORT) -> Classification:
    return Classification(documentName="Test document", documentType=doc_type, ownerName=name)


def owners(groups) -> list:
    return [g.ownerName for g in groups]


def main() -> None:
    # Mixed capitalisation and spacing, 2 people, plus documents with no owner.
    docs = [
        doc(None, DocumentType.UNKNOWN),
        doc("John Doe", DocumentType.TAX_RETURN),
        doc("MARIA DOE", DocumentType.AADHAAR),
        doc("JOHN DOE"),
        doc("john   doe", DocumentType.UNKNOWN),
        doc("Maria Doe"),
        doc(None, DocumentType.UNKNOWN),
    ]
    groups = group_by_owner(docs, lambda d: d.ownerName)
    check("2 owners + no-owner -> 3 groups, null last", owners(groups) == ["John Doe", "MARIA DOE", None], str(owners(groups)))
    check("John group has all 3 spellings, in input order", groups[0].documents == [docs[1], docs[3], docs[4]])
    check("Maria group has 2 documents", groups[1].documents == [docs[2], docs[5]])
    check("no-owner group has both null documents", groups[2].documents == [docs[0], docs[6]])
    check("every document appears exactly once", sum(len(g.documents) for g in groups) == len(docs))
    check("same objects returned, nothing copied or changed", all(any(d is x for g in groups for x in g.documents) for d in docs))

    check("empty input -> []", group_by_owner([], lambda d: d.ownerName) == [])

    only_null = group_by_owner([doc(None), doc(None)], lambda d: d.ownerName)
    check("only null owners -> one null group", owners(only_null) == [None] and len(only_null[0].documents) == 2)

    no_null = group_by_owner([doc("A B"), doc("C D")], lambda d: d.ownerName)
    check("no null owners -> no null group", owners(no_null) == ["A B", "C D"])

    similar = group_by_owner([doc("John Doe"), doc("Jon Doe"), doc("John Doe Jr")], lambda d: d.ownerName)
    check("similar names are NOT merged (no guessing)", owners(similar) == ["John Doe", "Jon Doe", "John Doe Jr"])

    # The raw helper also copes with values the Classification validator would normally clean up.
    raw = group_by_owner([("a", "  "), ("b", ""), ("c", " Sara  Lee "), ("d", "SARA LEE")], lambda t: t[1])
    check("blank / whitespace names go to the null group", owners(raw) == ["Sara Lee", None], str(owners(raw)))
    check("displayed name has spaces tidied", raw[0].ownerName == "Sara Lee" and [t[0] for t in raw[0].documents] == ["c", "d"])

    accents = group_by_owner([doc("José Núñez"), doc("JOSÉ NÚÑEZ")], lambda d: d.ownerName)
    check("accented names match across case", owners(accents) == ["José Núñez"] and len(accents[0].documents) == 2)

    print(f"\n{sum(results)}/{len(results)} passed")


if __name__ == "__main__":
    main()
