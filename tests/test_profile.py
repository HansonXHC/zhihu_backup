from zhihu_backup.extractors import profile as profile_ext


def test_profile_from_api():
    raw = {
        "url_token": "abc",
        "name": "测试用户",
        "headline": "一行简介",
        "avatar_url_template": "https://pic1.zhimg.com/{size}/avatar.jpg",
        "cover_url_template": "https://pica.zhimg.com/v2-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg?source=32738c0c",
        "url": "https://www.zhihu.com/api/v4/people/abc",
        "answer_count": 10,
        "articles_count": 2,
        "follower_count": 100,
        "following_count": 5,
        "description": "示例个人简介",
        "ip_info": "IP 属地示例地区",
        "business": {"name": "创意艺术"},
        "locations": [{"name": "示例地区"}],
        "employments": [
            {
                "company": {
                    "name": "示例机构",
                    "url": "https://www.zhihu.com/api/v4/topics/20035619",
                    "avatar_url": "https://picx.zhimg.com/v2-cccccccccccccccccccccccccccccccc_l.jpg",
                },
                "job": {"name": "示例职位"},
                "created": 1600000000,
            }
        ],
        "educations": [
            {
                "school": {
                    "name": "示例机构",
                    "avatar_url": "https://picx.zhimg.com/v2-school_l.jpg",
                },
                "major": {"name": "示例专业"},
                "diploma": {"name": "本科"},
            }
        ],
    }
    profile = profile_ext.from_api(raw, "abc")
    assert profile.name == "测试用户"
    assert profile.headline == "一行简介"
    assert profile.avatar_url == "https://picx.zhimg.com/xll/avatar.jpg"
    assert (
        profile.cover_url
        == "https://picx.zhimg.com/v2-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb_1440w.jpg"
    )
    assert profile.industry_logo_url == ""
    assert profile.url == "https://www.zhihu.com/people/abc"
    assert profile.answer_count == 10
    assert profile.follower_count == 100
    assert profile.description == "示例个人简介"
    assert profile.industry == "创意艺术"
    assert profile.locations == ["示例地区"]
    assert profile.ip_location == "示例地区"
    assert profile.employments[0]["company"] == "示例机构"
    assert profile.employments[0]["job"] == "示例职位"
    assert profile.employments[0]["company_url"].endswith("/topic/20035619")
    assert profile.employments[0]["logo_url"].endswith("_l.jpg")
    assert profile.educations[0]["school"] == "示例机构"
    assert profile.educations[0]["major"] == "示例专业"
    assert profile.educations[0]["diploma"] == "本科"
    assert profile.to_dict()["industry"] == "创意艺术"


def test_profile_from_api_description_fallback():
    raw = {"name": "无简介", "description": "备用简介"}
    profile = profile_ext.from_api(raw, "abc")
    assert profile.description == "备用简介"


def test_upgrade_avatar_url_to_xll():
    url = "https://picx.zhimg.com/v2-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_is.jpg"
    assert (
        profile_ext.upgrade_avatar_url(url)
        == "https://picx.zhimg.com/v2-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_xll.jpg"
    )
    template = "https://picx.zhimg.com/v2-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_{size}.jpg"
    assert (
        profile_ext.upgrade_avatar_url(template)
        == "https://picx.zhimg.com/v2-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_xll.jpg"
    )
    resized = "https://picx.zhimg.com/80/v2-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_l.jpg"
    assert (
        profile_ext.upgrade_avatar_url(resized)
        == "https://picx.zhimg.com/v2-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_xll.jpg"
    )
    actual_api_value = (
        "https://pica.zhimg.com/v2-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_l.jpg"
        "?source=32738c0c&needBackground=1"
    )
    assert (
        profile_ext.upgrade_avatar_url(actual_api_value)
        == "https://picx.zhimg.com/v2-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_xll.jpg"
    )


def test_clean_logo_url():
    actual_api_value = (
        "https://pic1.zhimg.com/v2-cccccccccccccccccccccccccccccccc_l.jpg"
        "?source=32738c0c"
    )
    assert (
        profile_ext.clean_image_url(actual_api_value, "l")
        == "https://picx.zhimg.com/v2-cccccccccccccccccccccccccccccccc_l.jpg"
    )


def test_upgrade_cover_url():
    actual = (
        "https://picx.zhimg.com/v2-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb_r.jpg"
        "?source=32738c0c"
    )
    expected = (
        "https://picx.zhimg.com/v2-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb_1440w.jpg"
    )
    assert profile_ext.upgrade_cover_url(actual) == expected
    template = (
        "https://pica.zhimg.com/v2-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg"
        "?source=32738c0c"
    )
    assert profile_ext.upgrade_cover_url(template) == expected


def test_profile_dom_headline_next_sibling():
    html = """
    <html><body>
      <h1 class="ProfileHeader-name">示例用户</h1>
      <span class="ProfileHeader-headline-extra">示例一句话简介 回答数 100，获得 1,000 次赞同</span>
    </body></html>
    """
    profile = profile_ext.from_dom(html, "example_user")
    assert profile.name == "示例用户"
    assert profile.headline == "示例一句话简介"


def test_profile_from_dom_with_detail_rows():
    html = """
    <html><head>
      <meta property="og:title" content="页面标题">
      <meta property="og:description" content="页面简介">
    </head><body>
      <h1 class="ProfileHeader-name">示例用户</h1>
      <div class="ProfileHeader-headline">示例一句话简介</div>
      <span>IP 属地示例地区</span>
      <div class="ProfileHeader-cover" style="background-image: url('//picx.zhimg.com/v2-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb_r.jpg?source=32738c0c')"></div>
      <img class="Avatar" src="//picx.zhimg.com/v2-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_l.jpg">
      <div class="ProfileHeader-info">
        <div class="ProfileHeader-infoItem">
          <span>所在行业</span><span>创意艺术</span>
        </div>
        <div class="ProfileHeader-infoItem">
          <span>职业经历</span>
          <img src="https://picx.zhimg.com/v2-cccccccccccccccccccccccccccccccc_l.jpg">
          <span>示例机构</span><span>·</span><span>示例职位</span>
        </div>
        <div class="ProfileHeader-infoItem">
          <span>教育经历</span>
          <img src="https://picx.zhimg.com/v2-school_l.jpg">
          <span>示例机构</span><span>·</span><span>示例专业</span>
        </div>
        <div class="ProfileHeader-infoItem">
          <span>个人简介</span><span>示例简介正文</span>
        </div>
      </div>
    </body></html>
    """
    profile = profile_ext.from_dom(html, "example_user")
    assert profile.name == "示例用户"
    assert profile.headline == "示例一句话简介"
    assert profile.avatar_url.endswith("_xll.jpg")
    assert profile.industry == "创意艺术"
    assert profile.description == "示例简介正文"
    assert profile.ip_location == "示例地区"
    assert (
        profile.cover_url
        == "https://picx.zhimg.com/v2-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb_1440w.jpg"
    )
    assert len(profile.employments) == 1
    assert profile.employments[0]["text"].startswith("示例机构")
    assert profile.employments[0]["logo_url"].endswith("_l.jpg")
    assert len(profile.educations) == 1
    assert profile.educations[0]["text"].startswith("示例机构")


def test_render_profile_markdown():
    profile = profile_ext.from_api(
        {
            "url_token": "abc",
            "name": "测试用户",
            "headline": "一行简介",
            "avatar_url": "https://pic1.zhimg.com/avatar_xll.jpg",
            "description": "个人简介",
            "ip_info": "IP 属地上海",
            "business": {"name": "创意艺术"},
            "employments": [
                {"company": {"name": "PCM"}, "job": {"name": "主任"}}
            ],
            "educations": [
                {"school": {"name": "PCM"}, "major": {"name": "作曲"}}
            ],
        },
        "abc",
    )
    profile.avatar_file = "avatar.jpg"
    profile.cover_file = "cover.jpg"
    profile.employments[0]["logo_file"] = "logos/employment_1.jpg"
    markdown = profile_ext.render_markdown(profile)
    assert markdown.startswith("# 测试用户")
    assert "![背景](cover.jpg)" in markdown
    assert "**所在行业**：创意艺术" in markdown
    assert "**IP 属地**：上海" in markdown
    assert "## 职业经历" in markdown
    assert "logos/employment_1.jpg" in markdown
    assert "PCM · 主任" in markdown
    assert "## 教育经历" in markdown
    assert "## 个人简介" in markdown
    assert "个人简介" in markdown
