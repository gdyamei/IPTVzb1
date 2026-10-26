# -*- coding: utf-8 -*-
"""把「阅读」(Legado) 订阅源转换成 TVBox 直播源（统一合并并去重）。

用法:
    python legado2tvbox.py [订阅源URL或本地JSON路径]

输出:
    hlive.txt   TVBox 直播源(txt 格式, 已删除重复源)
    hlive.json  TVBox 直播源(JSON lives 格式)
"""
from datetime import datetime
import gzip
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_SUB = "https://shuyuan.nyasama.net/shuyuan/a5b8ea7b35c86dd98eb9b1903d7db0d8.json"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
TIMEOUT = 20
WORKERS = 24

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def http_get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":  # gzip
        data = gzip.decompress(data)
    return data.decode("utf-8", "ignore")


def load_subscription(path_or_url):
    """优先取参数来源, 失败时回退到脚本同目录的 shuyuan.json。"""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        try:
            return json.loads(http_get(path_or_url))
        except Exception as e:
            print(f"[警告] 在线订阅源获取失败({e}), 尝试本地 shuyuan.json")
    local = os.path.join(OUT_DIR, "shuyuan.json")
    if os.path.exists(local):
        with open(local, "r", encoding="utf-8") as f:
            return json.load(f)
    if path_or_url.startswith("http"):
        raise e
    with open(path_or_url, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_groups(sub):
    """从订阅源的 sortUrl 提取 (分组名, 接口URL) 列表。"""
    groups = []
    for src in sub:
        sort = src.get("sortUrl") or ""
        for line in sort.splitlines():
            line = line.strip()
            if "::" in line:
                name, url = line.split("::", 1)
                groups.append((name.strip(), url.strip()))
    return groups


def fetch_group(name, url):
    """抓取单个分组接口, 返回 (分组名, [(频道名, 流地址), ...])。"""
    try:
        data = json.loads(http_get(url))
        chans = []
        for it in data.get("zhubo", []):
            title = str(it.get("title", "")).strip().replace(",", " ")
            addr = str(it.get("address", "")).strip()
            if title and addr.startswith("http"):
                chans.append((title, addr))
        return name, chans, None
    except Exception as e:
        return name, [], e


def main():
    sub_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SUB
    sub = load_subscription(sub_path)
    groups = extract_groups(sub)
    print(f"订阅源解析到 {len(groups)} 个分组")

    # 1. 多线程抓取所有源
    all_channels = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(fetch_group, n, u) for n, u in groups]
        for f in futures:
            name, chans, err = f.result()
            if err:
                print(f"[失败] {name}: {err}")
            elif chans:
                all_channels.extend(chans)
            else:
                print(f"[空] {name}")

    # 2. 全局过滤重复的 URL 链接，并保留唯一的频道
    seen_urls = set()
    unique_channels = {}  # 用 频道名 作为 key，对应的 url 列表作为 value
    
    for title, addr in all_channels:
        if addr not in seen_urls:
            seen_urls.add(addr)
            # 同名频道归类合并多线路，用 # 分隔
            unique_channels.setdefault(title, []).append(addr)

        # 获取北京时间（UTC+8）并格式化为 年-月-日-时:分秒
    from datetime import datetime, timezone, timedelta
    tz_bj = timezone(timedelta(hours=8))
    current_time_group = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M")
    # 获取当前时间并格式化为 年-月-日-时:分秒
    #current_time_group = datetime.now().strftime("%Y-%m-%d-%H:%M:%S")

    # 3. 输出 txt 格式: 全部归入当前时间分组
    txt_lines = []
    txt_lines.append(f"{current_time_group},#genre#")
    for title, urls in unique_channels.items():
        txt_lines.append(f"{title},{'#'.join(urls)}")
    
    txt_path = os.path.join(OUT_DIR, "hlive.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(txt_lines))

    # 4. 同时为了兼容格式，输出对应的单一分组 json lives 格式
    lives = {
        "lives": [
            {
                "group": current_time_group,
                "channels": [{"name": t, "urls": urls} for t, urls in unique_channels.items()],
            }
        ]
    }
    json_path = os.path.join(OUT_DIR, "hlive.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(lives, f, ensure_ascii=False, indent=2)

    print(f"\n处理完毕！")
    print(f"已将所有源合并至【{current_time_group}】分组，去重后共有 {len(unique_channels)} 个唯一频道 (共计 {len(seen_urls)} 条有效链接)")
    print(f"输出: {txt_path}")
    print(f"输出: {json_path}")


if __name__ == "__main__":
    main()
