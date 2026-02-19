FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

# Replace Ubuntu ports mirror before any package installation
# 按地区替换：中国大陆用 mirrors.aliyun.com，美国用 us.archive.ubuntu.com
RUN sed -i 's|http://ports.ubuntu.com|http://mirror.aarnet.edu.au|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || \
    sed -i 's|http://ports.ubuntu.com|http://mirror.aarnet.edu.au|g' /etc/apt/sources.list 2>/dev/null || true

# Refresh package index after mirror switch
RUN apt-get update
