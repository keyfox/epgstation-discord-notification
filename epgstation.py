#!/usr/bin/env python3
"""EPGStation notification provider"""

__author__ = "Keyfox"
__version__ = "1.0.0"
__license__ = "MIT"

import os
import argparse
from datetime import datetime, timedelta
import functools
import json

import urllib.request


def readable_datetime(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def readable_timedelta(td):
    # is there a smarter way to do this?
    seconds = int(td.total_seconds())
    minutes = seconds // 60
    hours = minutes // 60
    return f"{hours}:{minutes % 60:02d}:{seconds % 60:02d}"


def retrieve_envvars():
    def get_envvar(key, castfn=None):
        raw = os.environ.get(key, None)

        if raw is None or raw == "null":
            # what if `null` is actually the value...?
            return None

        if castfn:
            return castfn(raw)
        else:
            return raw

    def unixtime_str_to_datetime(unixtime_str):
        # for some reason we have to devide the unixtime by 1000...
        return datetime.fromtimestamp(int(unixtime_str) // 1000)

    def milliseconds_str_to_timedelta(milliseconds_str):
        return timedelta(seconds=int(milliseconds_str) // 1000)

    # https://github.com/l3tnun/EPGStation/blob/master/doc/conf-manual.md
    envvars_castfn = {
        "PROGRAMID": int,
        "RECORDEDID": int,
        "CHANNELTYPE": None,
        "CHANNELID": None,
        "CHANNELNAME": None,
        "STARTAT": unixtime_str_to_datetime,
        "ENDAT": unixtime_str_to_datetime,
        "DURATION": milliseconds_str_to_timedelta,
        "NAME": None,
        "DESCRIPTION": None,
        "EXTENDED": None,
        "RECPATH": None,
        "LOGPATH": None,
        "ERROR_CNT": int,
        "DROP_CNT": int,
        "SCRAMBLING_CNT": int,
    }

    return {key: get_envvar(key, castfn) for key, castfn in envvars_castfn.items()}


def send_discord_webhook(webhook_url, payload):
    # requests.post(webhook_url, json=payload)

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        # they rejects urllib...
        "User-Agent": "curl/7.64.1",
    }

    req = urllib.request.Request(webhook_url, data=body, method="POST", headers=headers)
    urllib.request.urlopen(req)


def try_comma_int(number, fallback):
    if number is None:
        return fallback
    return f"{number:,}"


def build_payload(message, color=None, envvars=None, artifacts=False):
    if envvars is None:
        envvars = retrieve_envvars()

    embed = {
        "title": f"{message}: {envvars['NAME']}",
        "description": envvars["DESCRIPTION"],
        "fields": [
            {
                "name": "チャンネル",
                "value": f"{envvars['CHANNELTYPE']}: {envvars['CHANNELID']} {envvars['CHANNELNAME'] or ''}",
            },
            {
                "name": "放送時間帯",
                "value": (
                    f"{readable_datetime(envvars['STARTAT'])} ～ {readable_datetime(envvars['ENDAT'])}\n"
                    f"`Duration` {readable_timedelta(envvars['DURATION'])}"
                ),
            },
        ],
    }

    if artifacts:
        embed["fields"].extend(
            [
                {"name": "録画ファイル", "value": f"```{envvars['RECPATH']}```"},
                {
                    "name": "ログファイル",
                    "value": envvars["LOGPATH"]
                    and f"```{envvars['LOGPATH']}```"
                    or "None",
                },
                {
                    "name": "エラー/ドロップ/スクランブル",
                    "value": (
                        f"`Error` {try_comma_int(envvars['ERROR_CNT'], 'N/A')}"
                        f"`Drop` {try_comma_int(envvars['DROP_CNT'], 'N/A')}"
                        f"`Scramble` {try_comma_int(envvars['SCRAMBLING_CNT'], 'N/A')}"
                    ),
                },
            ]
        )
    if color is not None:
        embed["color"] = color

    payload = {
        "embeds": [embed],
    }

    return payload


notifiers = []


def notifier(fn):
    @functools.wraps(fn)
    def wrapper(args):
        payload = fn(args)
        if payload is None:
            # Send nothing
            return
        webhook_url = args.config["webhook_url"]
        send_discord_webhook(webhook_url, payload)

    notifiers.append((fn.__name__, wrapper))
    return wrapper


@notifier
def reserve_new_addition(args):
    return build_payload(":bell: 録画予約追加")


@notifier
def reserve_update(args):
    return build_payload(":bell: 録画予約更新")


@notifier
def reserve_deleted(args):
    return build_payload(":no_bell: 録画予約削除")


@notifier
def recording_pre_start(args):
    return build_payload(":movie_camera: 録画準備開始", color=0xFFFFCC)


@notifier
def recording_prep_rec_failed(args):
    return build_payload(":no_entry: 録画準備失敗", color=0xFF0000)


@notifier
def recording_start(args):
    return build_payload(":record_button: 録画開始", artifacts=False, color=0xFFFFCC)


@notifier
def recording_finish(args):
    return build_payload(":stop_button: 録画終了", artifacts=True, color=0x00FF00)


@notifier
def recording_failed(args):
    return build_payload(":no_entry: 録画失敗", artifacts=True, color=0xFF0000)


def load_json_file(filepath):
    try:
        with open(filepath, "r") as f:
            loaded = json.load(f)
    except Exception as ex:
        raise ValueError from ex
    return loaded


if __name__ == "__main__":
    """ This is executed when run from the command line """
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s (version {version})".format(version=__version__),
    )
    parser.add_argument("--config", default="./config.json", type=load_json_file)

    subparsers = parser.add_subparsers(dest="cmd", required=True)
    for (name, fn) in notifiers:
        p = subparsers.add_parser(name)
        p.set_defaults(func=fn)

    args = parser.parse_args()
    args.func(args)
