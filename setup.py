from setuptools import setup, find_namespace_packages  # type: ignore

setup(
    name="clend",
    version="0.1.0",
    url="https://github.com/cleaner-bot/cleaner-bot",
    author="Leo Developer",
    author_email="git@leodev.xyz",
    description="cleaner demon",
    packages=find_namespace_packages(include=["clend*"]),
    package_data={"clend": ["py.typed"]},
)
