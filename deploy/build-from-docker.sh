#! /bin/sh

# This script runs inside the Docker container constructed by
# deploy/Dockerfile, and is responsible for the actual building of
# PhantomJS.  For this script to work correctly, /src/phantomjs/volume
# must be a host volume containing the exact git checkout you want
# built.  That is, normally this script should be invoked (from
# outside the container, but inside the git checkout) like so:
#
#  docker run -v $PWD:/src/phantomjs/volume phantomjs:2.1 [...other args...]
#
# If all goes well, the built phantomjs executable will be copied to
# /src/phantomjs/volume/bin, just as if you had built it on the host.

DO_NORMAL_TESTS=y
DO_GHOST_TESTS=y

while [ $# -gt 0 ]; do
    if [ x"$1" = x--skip-all-tests ]; then
        shift
        DO_NORMAL_TESTS=
        DO_GHOST_TESTS=
    elif [ x"$1" = x--skip-normal-tests ]; then
        shift
        DO_NORMAL_TESTS=
    elif [ x"$1" = x--skip-ghost-tests ]; then
        shift
        DO_GHOST_TESTS=
    else
        break
    fi
done

set -ex

cd /src/phantomjs

# sanity check
if [ ! -d volume/.git ] || \
   [ ! -f volume/build.py ] || \
   [ ! -f volume/src/phantom.cpp ]; then
    echo "/src/phantomjs/volume is not a Git checkout of PhantomJS." >&2
    exit 2
fi

[ -d build ] || mkdir build

cd volume
cp ./build.py ../build
git ls-files -z --exclude-standard src test | cpio -pdm0 --quiet ../build
git submodule foreach --recursive --quiet \
    'git ls-files -z --exclude-standard |
        cpio -pdm0 --quiet $toplevel/../build/$path'

# src/qt/qtbase/.git must exist, or else qtbase/configure will skip an
# essential step and the build will fail.  It doesn't need to contain
# anything.
touch ../build/src/qt/qtbase/.git

cd ../build

./build.py --confirm "$@"

[ -z "$DO_NORMAL_TESTS" ] || ./test/run-tests.py
[ -z "$DO_GHOST_TESTS" ]  || ./test/run-tests-ghostdriver.sh

cp bin/phantomjs ../volume/bin
