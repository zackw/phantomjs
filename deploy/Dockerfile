# This Dockerfile builds statically linked Linux binaries of PhantomJS.
# These should run in any Linux environment that is at least as new as
# Ubuntu 14.04 (Trusty).

# Baseline.  This is required to be the first instruction in a Dockerfile.
FROM ubuntu:14.04

# We build all library dependencies (other than glibc and libstdc++)
# from upstream sources to ensure distribution independence.  These
# variables set the versions we use.
# These are the latest release versions as of 2015-12-09.
ENV ZLIB_VER=1.2.8             \
    LIBPNG_VER=1.6.19          \
    LIBJPEG_TURBO_VER=1.4.2    \
    LIBWEBP_VER=0.4.4          \
    OPENSSL_VER=1.0.2e         \
    LIBXML2_VER=2.9.3          \
    LIBXSLT_VER=1.1.28         \
    FREETYPE_VER=2.6.2         \
    FONTCONFIG_VER=2.11.1      \
    ICU_VER=56.1               \
    ICU_FILE_VER=56_1

# Necessary tools from Ubuntu.
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        build-essential bison bzip2 cpio curl default-jdk flex git g++ gperf \
        nasm pkg-config python ruby tar

RUN mkdir -p /src/phantomjs
WORKDIR /src

# Download all the libraries.
# Depressingly, only OpenSSL offers integrity-protected download from the
# official site.  Many do offer PGP signatures but then we'd have to know
# which keys to trust for which packages, and we still wouldn't have 100%
# coverage.
RUN curl -sL http://zlib.net/zlib-${ZLIB_VER}.tar.gz | tar -xz
RUN curl -sL http://download.sourceforge.net/libpng/libpng-${LIBPNG_VER}.tar.gz | tar -xz
RUN curl -sL http://sourceforge.net/projects/libjpeg-turbo/files/${LIBJPEG_TURBO_VER}/libjpeg-turbo-${LIBJPEG_TURBO_VER}.tar.gz/download | tar -xz
RUN curl -sL http://downloads.webmproject.org/releases/webp/libwebp-${LIBWEBP_VER}.tar.gz | tar -xz
RUN curl -sL https://openssl.org/source/openssl-${OPENSSL_VER}.tar.gz | tar -xz
RUN curl -sL ftp://xmlsoft.org/libxml2/libxml2-sources-${LIBXML2_VER}.tar.gz | tar -xz
RUN curl -sL ftp://xmlsoft.org/libxml2/libxslt-${LIBXSLT_VER}.tar.gz | tar -xz
RUN curl -sL http://download.savannah.gnu.org/releases/freetype/freetype-${FREETYPE_VER}.tar.bz2 | tar -xj
RUN curl -sL http://www.freedesktop.org/software/fontconfig/release/fontconfig-${FONTCONFIG_VER}.tar.gz | tar -xz
RUN curl -sL http://download.icu-project.org/files/icu4c/${ICU_VER}/icu4c-${ICU_FILE_VER}-src.tgz | tar -xz

# Build all the libraries.

# zlib
RUN cd zlib-${ZLIB_VER} && ./configure --prefix=/usr --static && make all && make install

# libpng
RUN cd libpng-${LIBPNG_VER} && ./configure --prefix=/usr --enable-static --disable-shared && make all && make install

# libjpeg-turbo
RUN cd libjpeg-turbo-${LIBJPEG_TURBO_VER} && ./configure --prefix=/usr --enable-static --disable-shared && make all && make install

# libwebp
RUN cd libwebp-${LIBWEBP_VER} && ./configure --prefix=/usr --enable-static --disable-shared && make all && make install

# OpenSSL
RUN cd openssl-${OPENSSL_VER} && ./config --prefix=/usr --openssldir=/etc/ssl --libdir=lib && make all && make install

# libxml2
RUN cd libxml2-${LIBXML2_VER} && ./configure --help && ./configure --prefix=/usr --enable-static --disable-shared --with-python=no && make all && make install

# libxslt
RUN cd libxslt-${LIBXSLT_VER} && ./configure --prefix=/usr --enable-static --disable-shared && make all && make install

# Freetype
RUN cd freetype-${FREETYPE_VER} && ./configure --prefix=/usr --enable-static --disable-shared && make all && make install

# Fontconfig
RUN cd fontconfig-${FONTCONFIG_VER} && ./configure --prefix=/usr --enable-static --disable-shared --enable-libxml2 && make all && make install

# libicu
RUN cd icu/source && ./configure --prefix=/usr --enable-static --disable-shared && make all && make install

# Prepare to build PhantomJS itself.
# This is done by the entrypoint, so you can reuse the docker image for multiple builds.
RUN        mkdir -p /src/phantomjs /src/phantomjs/volume /src/phantomjs/build
WORKDIR    /src/phantomjs
COPY       build-from-docker.sh ./
ENTRYPOINT ["./build-from-docker.sh"]
