import typing

SCHEMES = ("http", "https")


def has_url(content: str) -> bool:
    for scheme in SCHEMES:
        if f"{scheme}://" in content:
            return True
    return False


def get_urls(content: str) -> typing.Generator[str, None, None]:
    words = content.split()
    for word in words:
        if "://" not in word:
            continue

        # urls can start anywhere in a word
        # eg: testhttp://test.com is valid
        for scheme in SCHEMES:
            if f"{scheme}://" in word:
                break
        else:
            continue

        start = word.index(f"{scheme}://")
        url = word[start + len(scheme) + 3 :]
        if url.endswith(")"):
            # handle urls with () in their path correctly
            # test.com/) -> test.com
            # test.com/() -> test.com()
            # test.com/()) -> test.com()
            count = url.count("(") - url.count(")")
            url = url[:-1] if count < 0 else url
        else:
            url = url.rstrip("]")

        # protocol://\test.com embeds but doesn't appear clickable,
        # but lets still parse that correctly
        if url.startswith("\\"):
            url = url.lstrip("\\/")

        yield scheme + "://" + url


def remove_urls(content: str) -> str:
    # remove the urls, starting with longest first
    # imagine this example: "http://test.com/ http//test.com/abcdef"
    # would keep "/abcdef"
    urls = list(get_urls(content))
    urls.sort(key=len, reverse=True)
    for url in urls:
        content = content.replace(url, "")
    return content


def domain_in_list(domain: str, collection: typing.Sequence[str]) -> bool:
    if domain in collection:
        return True
    for hostname in collection:
        if domain.endswith("." + hostname):
            return True
    return False
