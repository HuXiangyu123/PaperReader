from src.verification.source_tiers import classify_url


# Tier A
def test_arxiv():
    assert classify_url("https://arxiv.org/abs/1706.03762") == "A"


def test_doi():
    assert classify_url("https://doi.org/10.1234/example") == "A"


def test_semanticscholar():
    assert classify_url("https://www.semanticscholar.org/paper/123") == "A"


def test_neurips():
    assert classify_url("https://proceedings.neurips.cc/paper/2020") == "A"


def test_openreview():
    assert classify_url("https://openreview.net/forum?id=xyz") == "A"


def test_acm():
    assert classify_url("https://dl.acm.org/doi/10.1145/12345") == "A"


# Tier B
def test_github():
    assert classify_url("https://github.com/user/repo") == "B"


def test_huggingface():
    assert classify_url("https://huggingface.co/models") == "B"


def test_paperswithcode():
    assert classify_url("https://paperswithcode.com/method/transformer") == "B"


# Tier C
def test_wikipedia():
    assert classify_url("https://en.wikipedia.org/wiki/Transformer") == "C"


def test_stackoverflow():
    assert classify_url("https://stackoverflow.com/questions/123") == "C"


def test_edu_domain():
    assert classify_url("https://cs.stanford.edu/~paper.pdf") == "C"


def test_gov_domain():
    assert classify_url("https://www.nih.gov/research") == "C"


# Tier D
def test_unknown_domain():
    assert classify_url("https://random-blog.xyz/post") == "D"


def test_empty_url():
    assert classify_url("") == "D"


def test_invalid_url():
    assert classify_url("not a url") == "D"


def test_none_like():
    assert classify_url("ftp://something") == "D"
