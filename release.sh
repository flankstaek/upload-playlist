#!/usr/bin/env bash
set -euo pipefail

version="${1:-v$(date +%Y.%m.%d)}"
version="${version#v}"
tag="v${version}"

if [ -n "$(git status --porcelain)" ]; then
    echo "Working tree is dirty. Commit or stash changes first."
    exit 1
fi

if git rev-parse "$tag" >/dev/null 2>&1; then
    echo "Tag $tag already exists — deleting and retagging at HEAD."
    git tag -d "$tag"
    git push all --delete "$tag"
fi

sed -i "s/^Version = .*/Version = \"${version}\"/" PLUGININFO

if git diff --quiet PLUGININFO; then
    echo "PLUGININFO already at ${version}, tagging current HEAD."
else
    git add PLUGININFO
    git commit -m "Release ${tag}"
fi

# Annotated tag (-a): the Tangled release workflow derives the artifact's tag
# hash via `git rev-parse "<tag>^{tag}"`, which only resolves for a tag object.
git tag -a "$tag" -m "Release ${tag}"
git push all main --tags

echo "Released ${tag}"
