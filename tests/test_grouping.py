"""app/services/grouping.py: group documents by owner name."""

from app.schemas.classification import Classification, DocumentType
from app.services.grouping import group_by_owner


def doc(name: str | None, doc_type: DocumentType = DocumentType.PASSPORT) -> Classification:
    return Classification(documentName="Test document", documentType=doc_type, ownerName=name)


def owner_of(d: Classification) -> str | None:
    return d.ownerName


def owners(groups) -> list:
    return [g.ownerName for g in groups]


def test_mixed_spellings_two_owners_and_no_owner():
    docs = [
        doc(None, DocumentType.UNKNOWN),
        doc("John Doe", DocumentType.TAX_RETURN),
        doc("MARIA DOE", DocumentType.AADHAAR),
        doc("JOHN DOE"),
        doc("john   doe", DocumentType.UNKNOWN),
        doc("Maria Doe"),
        doc(None, DocumentType.UNKNOWN),
    ]
    groups = group_by_owner(docs, owner_of)
    assert owners(groups) == ["John Doe", "MARIA DOE", None]  # first spelling shown, null group last
    assert groups[0].documents == [docs[1], docs[3], docs[4]]  # input order kept
    assert groups[1].documents == [docs[2], docs[5]]
    assert groups[2].documents == [docs[0], docs[6]]
    assert sum(len(g.documents) for g in groups) == len(docs)  # every document exactly once
    assert all(any(d is x for g in groups for x in g.documents) for d in docs)  # same objects, not copies


def test_empty_input():
    assert group_by_owner([], owner_of) == []


def test_only_null_owners_give_one_null_group():
    groups = group_by_owner([doc(None), doc(None)], owner_of)
    assert owners(groups) == [None] and len(groups[0].documents) == 2


def test_no_null_owners_give_no_null_group():
    assert owners(group_by_owner([doc("A B"), doc("C D")], owner_of)) == ["A B", "C D"]


def test_similar_names_are_not_merged():
    groups = group_by_owner([doc("John Doe"), doc("Jon Doe"), doc("John Doe Jr")], owner_of)
    assert owners(groups) == ["John Doe", "Jon Doe", "John Doe Jr"]


def test_blank_names_go_to_null_group_and_spaces_are_tidied():
    groups = group_by_owner([("a", "  "), ("b", ""), ("c", " Sara  Lee "), ("d", "SARA LEE")], lambda t: t[1])
    assert owners(groups) == ["Sara Lee", None]
    assert [t[0] for t in groups[0].documents] == ["c", "d"]


def test_accented_names_match_across_case():
    groups = group_by_owner([doc("José Núñez"), doc("JOSÉ NÚÑEZ")], owner_of)
    assert owners(groups) == ["José Núñez"] and len(groups[0].documents) == 2
