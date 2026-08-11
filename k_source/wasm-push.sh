#!/bin/bash
set -e

if [ ! -d .git ]; then
 echo 'This script must be run from the root of the git repo' >&2
 exit 1
fi

git checkout master
gmake c # clean
gmake w # build wasm files

git checkout pages
cp o/w/index.html o/w/k.wasm o/w/k.wasm.lz4 .
cp o/w/x/tetris.k o/w/x/fractals.k o/w/x/mines.k x/
git add .
git commit -m wasm
git push

git checkout master

firefox --private-window 'https://ngn.codeberg.page/k/#eJwzVDDSNgYAApkA4g=='
