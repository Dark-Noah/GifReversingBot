import json
import subprocess


def get_duration(filestream):
    p = subprocess.Popen(
        ["ffprobe", "-i", "pipe:0", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    output = p.communicate(input=filestream.read())[0].decode("utf-8")
    data = json.loads(output)
    return float(data['format']['duration'])


def resetfile(file):
    #print(type(file))
    if not str(type(file)) == "<class 'http.client.HTTPResponse'>":
        #print(file.tell())
        if not file.tell() == 0:
            #print("seeking")
            file.seek(0)

def get_fps(filestream):
    p = subprocess.Popen(
        ["ffprobe", "-i", "pipe:0", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    raw_fps = json.loads(p.communicate(input=filestream.read())[0].decode("utf-8"))["streams"][0]["r_frame_rate"].split("/")
    fps = int(raw_fps[0]) / int(raw_fps[1])
    return fps