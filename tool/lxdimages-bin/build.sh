#!/bin/bash

echo "开始交叉编译 lxdimages..."

rm -f lxdimages-*

echo "编译 Linux amd64..."
GOOS=linux GOARCH=amd64 go build -o lxdimages-amd64 .

echo "编译 Linux arm64..."
GOOS=linux GOARCH=arm64 go build -o lxdimages-arm64 .

echo "编译完成！"
ls -la lxdimages-*