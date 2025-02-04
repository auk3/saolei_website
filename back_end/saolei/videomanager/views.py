# -*- coding: utf-8 -*-
import logging
logger = logging.getLogger(__name__)
from django.contrib.auth.decorators import login_required
from .forms import UploadVideoForm
from .models import VideoModel, ExpandVideoModel
from .view_utils import update_personal_record, update_personal_record_stock, video_all_fields
from userprofile.models import UserProfile
from django.http import HttpResponse, JsonResponse, FileResponse
import json, urllib
from utils import ComplexEncoder
from django.core.paginator import Paginator
from msuser.models import UserMS
from django.db.models import Q
# import os
# import time
from datetime import datetime
# from django.core.cache import cache
from django_redis import get_redis_connection
cache = get_redis_connection("saolei_website")
from django.shortcuts import render, redirect
# https://django-ratelimit.readthedocs.io/en/stable/rates.html
from django_ratelimit.decorators import ratelimit
from django.utils import timezone
# import ms_toollib as ms
from django.utils.encoding import escape_uri_path
from config.flags import DESIGNATOR_SKIP
from django.conf import settings


@login_required(login_url='/')
def video_upload(request):
    if request.method == 'POST':
        if request.user.is_banned:
            return JsonResponse({"status": 101, "msg": "用户被封禁!"})
        if request.user.userms.video_num_total >= request.user.userms.video_num_limit:
            return JsonResponse({"status": 188, "msg": "用户录像仓库已满!"})
            
        # response = {'status': 100, 'msg': None}
        # request.POST['file'] = request.FILES
        video_form = UploadVideoForm(data=request.POST, files=request.FILES)
        # print(video_form)
        if video_form.is_valid():
            data = video_form.cleaned_data
            if DESIGNATOR_SKIP and data["designator"] not in request.user.userms.designators:
                request.user.userms.designators.append(data["designator"])
                request.user.userms.save(update_fields=["designators"])
            if data["designator"] not in request.user.userms.designators:
                # 如果标识是首次使用的，需要得到管理员的审核
                data['review_code'] = 2

            # 查重
            collisions = list(VideoModel.objects.filter(timems=data["timems"], bv=data["bv"]).filter(video__cl=data["cl"], video__op=data["op"], video__isl=data["isl"], video__designator=data["designator"]))
            if collisions:
                return JsonResponse({"status": 200, "msg": "录像已存在"})
            
            # 表中添加数据
            e_video = ExpandVideoModel.objects.create(designator=data["designator"],
                                                      left=data["left"], right=data["right"],
                                                      double=data["double"], cl=data["cl"],
                                                      left_s=data["left_s"], right_s=data["right_s"],
                                                      double_s=data["double_s"], cl_s=data["cl_s"],
                                                      path=data["path"], flag=data["flag"],
                                                      flag_s=data["flag_s"], stnb=data["stnb"],
                                                      rqp=data["rqp"], ioe=data["ioe"],
                                                      thrp=data["thrp"], corr=data["corr"],
                                                      ce=data["ce"], ce_s=data["ce_s"],
                                                      op=data["op"], isl=data["isl"],
                                                      cell0=data["cell0"], cell1=data["cell1"],
                                                      cell2=data["cell2"], cell3=data["cell3"],
                                                      cell4=data["cell4"], cell5=data["cell5"],
                                                      cell6=data["cell6"], cell7=data["cell7"],
                                                      cell8=data["cell8"])
            # 会检查是否为盲扫，自动修改模式
            video = VideoModel.objects.create(player=request.user, file=data["file"], video=e_video,
                                      state=["c", "b", "a", "a"][data['review_code']], software=data["software"], level=data["level"],
                                      mode=data["mode"] if data["mode"]!="00" else ("12" if data["flag"]==0 else "00"), 
                                      timems=data["timems"],
                                      bv=data["bv"], bvs=data["bvs"])
            
            # cache.hget("review_queue", "filed")
            temp = json.dumps({"time": video.upload_time,
                                "player": video.player.realname,
                                "player_id": video.player.id,
                                "level": video.level,
                                "mode": video.mode,
                                "timems": video.timems,
                                "bv": video.bv,
                                "bvs": video.bvs}, cls=ComplexEncoder)
            if data['review_code'] >= 2:
                # 往审查队列里添加录像
                cache.hset("review_queue", video.id, temp)
            else:
                # 如果录像自动通过了审核，更新最新录像和纪录
                cache.hset("newest_queue", video.id, temp)
                update_personal_record(video)
                update_video_num(video)
                

            # review_video_ids = cache.hgetall("review_queue")
            # print(review_video_ids)

            # update_personal_record(request, data, e_video)
            return JsonResponse({"status": 100, "msg": None})
        else:
            # print(video_form.errors)
            return JsonResponse({"status": 666, "msg": "小型网站，请勿攻击！"})
    elif request.method == 'GET':
        return HttpResponse("别瞎玩")
    else:
        return HttpResponse("别瞎玩")

# 根据id向后台请求软件类型（适配flop播放器用）
def get_software(request):
    if request.method != 'GET':
        return HttpResponse("别瞎玩")
    try:
        video = VideoModel.objects.get(id=request.GET["id"])
        # print({"status": 100, "msg": video.software})
        return JsonResponse({"status": 100, "msg": video.software})
    except Exception:
        return JsonResponse({"status": 104, "msg": "file not exist!"})

# 给预览用的接口，区别是结尾是文件后缀
# 坑：如果做成必须登录才能下载，由于Django的某种特性，会重定向资源，
# 然而flop播放器不能处理此状态码，因此会请求到空文件，导致解码失败
@ratelimit(key='ip', rate='20/m')
def video_preview(request):
    if request.method != 'GET':
        return HttpResponse("别瞎玩")
    # 这里性能可能有问题
    try:
        video = VideoModel.objects.get(id=int(request.GET["id"][:-4]))
        # video.file.name是相对路径(含upload_to)，video.file.path是绝对路径
        print(settings.MEDIA_ROOT / "assets" / video.file.name)
        file_path = settings.MEDIA_ROOT / "assets" / video.file.name
        response =FileResponse(open(file_path, 'rb'))
        response['Content-Type']='application/octet-stream'
        # response['Content-Disposition']=f'attachment;filename="{video.file.name.split("/")[2]}"'
        file_name = video.file.name.split("/")[2]
        file_name_uri = urllib.parse.quote(file_name)
        response['Content-Disposition'] = f'attachment; filename="{file_name_uri}"'
        response['Access-Control-Expose-Headers']='Content-Disposition'
        
        return response
    except Exception:
        return JsonResponse({"status": 104, "msg": "file not exist!"})

# 给下载用的接口，区别是结尾没有文件后缀
# @login_required(login_url='/')
@ratelimit(key='ip', rate='20/m')
def video_download(request):
    if request.method != 'GET':
        return HttpResponse("别瞎玩")
    try:
        video = VideoModel.objects.get(id=request.GET["id"])
        response =FileResponse(open(video.file.path, 'rb'))
        response['Content-Type']='application/octet-stream'
        response['Content-Disposition']=f'attachment;filename="{video.file.name.split("/")[2]}"'
        return response
    except VideoModel.DoesNotExist:
        return JsonResponse({"status": 104, "msg": "录像不存在！"})
    # try:
    #     video = VideoModel.objects.get(id=request.GET["id"])
    #     response =FileResponse(open(video.file.path, 'rb'))
    #     response['Content-Type']='application/octet-stream'
    #     response['Content-Disposition']=f'attachment;filename="{video.file.name.split("/")[2]}"'
    #     return response
    # except Exception:
    #     return JsonResponse({"status": 104, "msg": "file not exist!"})

# 录像查询（无需登录）
# 按任何基础指标+难度+模式，排序，分页
# 每项的定义参见 front_end/src/views/VideoView.vue 的 request_videos 函数
@ratelimit(key='ip', rate='20/m')
def video_query(request):
    if request.method == 'GET':
        data = request.GET

        values = video_all_fields

        if data["r"] == "true":
            ob = "-" + data["o"]
        else:
            ob = data["o"]
        if data["o"] != "timems":
            orderby = (ob, "timems")
        else:
            orderby = (ob,)
            
        if data["mode"] != "00":
            filter = {"level": data["level"], "mode": data["mode"]}
            videos = VideoModel.objects.filter(**filter).order_by(*orderby).values(*values)
        else:
            filter = {"level": data["level"]}
            videos = VideoModel.objects.filter(Q(mode="00")|Q(mode="12")).filter(**filter).order_by(*orderby).values(*values)

        # print(videos)
        paginator = Paginator(videos, data["ps"])
        page_number = data["page"]
        page_videos = paginator.get_page(page_number)
        response = {
            "count": len(videos),
            "videos": list(page_videos)
            }
        # t=json.dumps(response, cls=ComplexEncoder)
        # print(t)
        return JsonResponse(json.dumps(response, cls=ComplexEncoder), safe=False)

    elif request.method == 'POST':
        return HttpResponse("别瞎玩")
    else:
        return HttpResponse("别瞎玩")


# 按id查询这个用户的所有录像
def video_query_by_id(request):
    if request.method == 'GET':
        id_ = request.GET["id"]
        
        user = UserProfile.objects.get(id=id_)
        videos = VideoModel.objects.filter(player=user).values('id', 'upload_time', "level", "mode", "timems", "bv", "bvs")
        # print(list(videos))

        return JsonResponse(json.dumps({"videos": list(videos)}, cls=ComplexEncoder), safe=False)
    else:
        return HttpResponse("别瞎玩")


# {
#     "1": "{\"time\": \"2023-12-16 14:52:40\", \"player\": \"\\u5b9e\\u540d\", \"level\": \"b\", \"mode\": \"00\", \"timems\": \"4770\", \"bv\": 23, \"bvs\": 4.821802935010482}",
#     "3": "{\"time\": \"2023-12-16 14:52:52\", \"player\": \"\\u5b9e\\u540d\", \"level\": \"i\", \"mode\": \"00\", \"timems\": \"20390\", \"bv\": 71, \"bvs\": 3.4330554193231975}",
#     "4": "{\"time\": \"2023-12-16 15:17:58\", \"player\": \"\\u5b9e\\u540d\", \"level\": \"b\", \"mode\": \"12\", \"timems\": \"1530\", \"bv\": 4, \"bvs\": 2.6143790849673203}",
#     "8": "{\"time\": \"2023-12-16 15:26:22\", \"player\": \"www333\", \"level\": \"e\", \"mode\": \"00\", \"timems\": \"51940\", \"bv\": 149, \"bvs\": 2.849441663457836}",
#     "9": "{\"time\": \"2023-12-16 15:26:26\", \"player\": \"www333\", \"level\": \"b\", \"mode\": \"00\", \"timems\": \"3250\", \"bv\": 18, \"bvs\": 5.538461538461538}",
#     "10": "{\"time\": \"2023-12-16 15:26:30\", \"player\": \"www333\", \"level\": \"i\", \"mode\": \"00\", \"timems\": \"20110\", \"bv\": 69, \"bvs\": 3.431128791645947}",
#     "7": "{\"time\": \"2023-12-16 15:24:07\", \"player\": \"\\u5b9e\\u540d\", \"level\": \"i\", \"mode\": \"00\", \"timems\": \"15280\", \"bv\": 31, \"bvs\": 2.0287958115183247}",
#     "6": "{\"time\": \"2023-12-16 15:24:02\", \"player\": \"\\u5b9e\\u540d\", \"level\": \"e\", \"mode\": \"00\", \"timems\": \"59450\", \"bv\": 193, \"bvs\": 3.2127838519764507}",
#     "2": "{\"time\": \"2023-12-16 14:52:48\", \"player\": \"\\u5b9e\\u540d\", \"level\": \"e\", \"mode\": \"00\", \"timems\": \"61710\", \"bv\": 193, \"bvs\": 3.0789175174201913}",
#     "5": "{\"time\": \"2023-12-16 15:23:59\", \"player\": \"\\u5b9e\\u540d\", \"level\": \"b\", \"mode\": \"12\", \"timems\": \"1580\", \"bv\": 6, \"bvs\": 3.7974683544303796}"
# }


# 上传的录像进入数据库后，更新用户的录像数目
def update_video_num(video: VideoModel, add = True):
    userms = video.player.userms
    # add = True：新增录像；add = False：删除录像
    if video.mode == '00':
        userms.video_num_std += 1 if add else -1
    elif video.mode == '12':
        userms.video_num_nf += 1 if add else -1
    elif video.mode == '05':
        userms.video_num_ng += 1 if add else -1
    elif video.mode == '11':
        userms.video_num_dg += 1 if add else -1

    if video.level == "b":
        userms.video_num_beg += 1 if add else -1
    elif video.level == 'i':
        userms.video_num_int += 1 if add else -1
    elif video.level == 'e':
        userms.video_num_exp += 1 if add else -1

    if add:
        # 给高玩自动扩容
        if video.mode == "00" and video.level == 'e':
            if video.timems < 100000 and userms.video_num_limit < 200:
                userms.video_num_limit = 200
            if video.timems < 60000 and userms.video_num_limit < 500:
                userms.video_num_limit = 500
            if video.timems < 50000 and userms.video_num_limit < 600:
                userms.video_num_limit = 600
            if video.timems < 40000 and userms.video_num_limit < 800:
                userms.video_num_limit = 800
            if video.timems < 30000 and userms.video_num_limit < 1000:
                userms.video_num_limit = 1000
    
    userms.save(update_fields=["video_num_limit", "video_num_total", "video_num_beg", "video_num_int", 
                               "video_num_exp", "video_num_std", "video_num_nf", "video_num_ng", 
                               "video_num_dg"])



# 获取审查队列里的录像
# http://127.0.0.1:8000/video/review_queue
def review_queue(request):
    if request.method == 'GET':
        review_video_ids = cache.hgetall("review_queue")
        for key in list(review_video_ids.keys()):
            review_video_ids.update({str(key, encoding="utf-8"): review_video_ids.pop(key)})
        return JsonResponse(review_video_ids, encoder=ComplexEncoder)
    else:
        return HttpResponse("别瞎玩")

# 获取最新录像
# http://127.0.0.1:8000/video/newest_queue
def newest_queue(request):
    if request.method == 'GET':
        newest_queue_ids = cache.hgetall("newest_queue")
        for key in list(newest_queue_ids.keys()):
            newest_queue_ids.update({str(key, encoding="utf-8"): newest_queue_ids.pop(key)})
        return JsonResponse(newest_queue_ids, encoder=ComplexEncoder)
    else:
        return HttpResponse("别瞎玩")
    

# 获取谁破纪录的消息
# http://127.0.0.1:8000/video/news_queue
def news_queue(request):
    if request.method == 'GET':
        news_queue = cache.lrange("news_queue", 0, -1)
        return JsonResponse(news_queue, encoder=ComplexEncoder, safe=False)
    else:
        return HttpResponse("别瞎玩")
    
    
# 获取全网被冻结的录像
# http://127.0.0.1:8000/video/freeze_queue
def freeze_queue(request):
    if request.method == 'GET':
        freeze_queue_ids = cache.hgetall("freeze_queue")
        for key in list(freeze_queue_ids.keys()):
            freeze_queue_ids.update({str(key, encoding="utf-8"): freeze_queue_ids.pop(key)})
        return JsonResponse(freeze_queue_ids, encoder=ComplexEncoder)
    else:
        return HttpResponse("别瞎玩")
    

# 【管理员】审核通过队列里的录像，未审核或冻结状态的录像可以审核通过
# 返回"True","False"（已经是通过的状态）,"Null"（不存在该录像）
# http://127.0.0.1:8000/video/approve?ids=[18,19,999]
def approve(request):
    if request.user.is_staff and request.method == 'GET':
        ids = json.loads(request.GET["ids"])
        # logger.info(f'{request.user.id} approve ids {ids}')
        res = []
        for _id in ids:
            if not isinstance(_id, int):
                return HttpResponse("审核录像的id应为正整数。")
            video_i = VideoModel.objects.filter(id=_id)
            if not video_i:
                res.append("Null")
            else:
                video_i = video_i[0]
                e_video = video_i.video
                if video_i.state == "c":
                    # 已经通过审核了
                    res.append("False")
                else:
                    # 录像通过审核
                    ms_player = video_i.player.userms
                    if e_video.designator not in ms_player.designators:
                        # 给用户增加新的标识
                        ms_player.designators.append(e_video.designator)
                        ms_player.save(update_fields=["designators"])
                    video_i.state = "c"
                    video_i.upload_time = timezone.now()
                    res.append("True")
                    video_i.save()
                    cache.hset("newest_queue", _id, cache.hget("review_queue", _id))
                    update_personal_record(video_i)
                    update_video_num(video_i)
                cache.hdel("review_queue", _id)
        # logger.info(f'{request.user.id} approve {json.dumps(ids)} response {json.dumps(res)}')
        return JsonResponse(json.dumps(res), safe=False)
    else:
        return HttpResponse("别瞎玩")

# 【管理员】冻结队列里的录像，未审核或审核通过的录像可以冻结
# 两种用法，冻结指定的录像id，或冻结某用户的所有录像
# 冻结的录像七到14天后删除，用一个定时任务
# http://127.0.0.1:8000/video/freeze?ids=[18,19,20,21,102,273]
# http://127.0.0.1:8000/video/freeze?ids=12
# http://127.0.0.1:8000/video/freeze?user_id=20
def freeze(request):
    if request.user.is_staff and request.method == 'GET':
        if _ids := request.GET["ids"]:
            logger.info(f'{request.user.id} freeze ids {_ids}')
            ids = json.loads(_ids)
            if isinstance(ids, int):
                ids = [ids]
        else: 
            _user_id = int(request.GET["user_id"])
            logger.info(f'{request.user.id} freeze user_id {_user_id}')
            user = UserProfile.objects.get(id=_user_id)
            videos = VideoModel.objects.filter(player=user)
            ids = []
            for v in videos:
                ids.append(v.id)
                
        res = [] 
        for _id in ids:
            if not isinstance(_id, int) or _id < 1:
                return HttpResponse("冻结录像的id应为正整数。")
            video_i = VideoModel.objects.filter(id=_id)
            if not video_i:
                res.append("Null")
            else:
                video_i = video_i[0]
                if video_i[0].state == "b":
                    res.append("False")
                else:
                    # 冻结成功
                    video_i.state = "b"
                    video_i.upload_time = timezone.now()
                    res.append("True")
                    video_i.save()
                    cache.hset("freeze_queue", _id, json.dumps({"time": video_i.upload_time,
                                                                "player": video_i.player.realname,
                                                                "player_id": video_i.player.id,
                                                                "level": video_i.level,
                                                                "mode": video_i.mode,
                                                                "timems": video_i.timems,
                                                                "bv": video_i.bv,
                                                                "bvs": video_i.bvs}, cls=ComplexEncoder))
                    if request.GET["ids"]:
                        update_personal_record_stock(video_i.player)
                    update_video_num(video_i, add=False)
                cache.hdel("review_queue", _id)
                cache.hdel("newest_queue", _id)
        if request.GET["user_id"]:
            update_personal_record_stock(user)
        logger.info(f'{request.user.id} freeze {json.dumps(ids)} response {json.dumps(res)}')
        return JsonResponse(json.dumps(res), safe=False)
    else:
        return HttpResponse("别瞎玩")





