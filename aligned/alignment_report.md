# PSF Survey 跨年数据对齐报告

生成时间：2026-10-10 17:30

管线：文本归一 + 组路径重映射 + 同义词表 -> 列名统一 -> 取值文案统一 -> 共有列纵向合并

## 对齐统计

- 跨年共有列：153（对齐前为 42）
- 重命名列：382
- 取值统一记录：109745
- 跨年总表行数：185632

| 年份 | 总列数 | 落在共有列中的列数 |
|---|---|---|
| 2019 | 290 | 153 |
| 2020 | 264 | 153 |
| 2021 | 387 | 153 |
| 2022 | 403 | 153 |
| 2023 | 491 | 153 |
| 2024 | 573 | 153 |

### 列名重命名按年份统计

| 年份 | 重命名列数 |
|---|---|
| 2019 | 201 |
| 2020 | 31 |
| 2021 | 48 |
| 2022 | 43 |
| 2023 | 25 |
| 2024 | 34 |

### 重命名示例（每年前 8 条）

**2019**
- `what_other_language_s_do_you_use[Other - Write In]` -> `other.lang.Other - Write In`
- `for_what_purposes_do_you_mainly_use_python` -> `main.purposes`
- `what_do_you_use_python_for[Computer graphics]` -> `other.purposes.Computer graphics`
- `what_do_you_use_python_for[Data analysis]` -> `other.purposes.Data analysis`
- `what_do_you_use_python_for[Desktop development]` -> `other.purposes.Desktop development`
- `what_do_you_use_python_for[DevOps / System administration / Writing automation scripts]` -> `other.purposes.DevOps / System administration / Writing automation scripts`
- `what_do_you_use_python_for[Educational purposes]` -> `other.purposes.Educational purposes`
- `what_do_you_use_python_for[Embedded development]` -> `other.purposes.Embedded development`
**2020**
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`
- `python.version.upgrade.OS-provided Python (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-provided Python`
- `isolate.environments.None` -> `environments.isolate.None`
- `isolate.environments.Virtualenv` -> `environments.isolate.virtualenv`
- `isolate.environments.Pipenv` -> `environments.isolate.Pipenv`
- `isolate.environments.Poetry` -> `environments.isolate.Poetry`
- `isolate.environments.Conda` -> `environments.isolate.Conda`
- `isolate.environments.Docker` -> `environments.isolate.Docker`
**2021**
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`
- `python.version.upgrade.OS-provided Python (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-provided Python`
- `isolate.environments.None` -> `environments.isolate.None`
- `isolate.environments.Virtualenv` -> `environments.isolate.virtualenv`
- `isolate.environments.Pipenv` -> `environments.isolate.Pipenv`
- `isolate.environments.Poetry` -> `environments.isolate.Poetry`
- `isolate.environments.Conda` -> `environments.isolate.Conda`
- `isolate.environments.Docker` -> `environments.isolate.Docker`
**2022**
- `how.involved.Other - Write In:` -> `how.involved.Other - Write In`
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`
- `python.version.upgrade.OS-provided Python (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-provided Python`
- `isolate.environments.None` -> `environments.isolate.None`
- `isolate.environments.Virtualenv` -> `environments.isolate.virtualenv`
- `isolate.environments.Pipenv` -> `environments.isolate.Pipenv`
- `isolate.environments.Poetry` -> `environments.isolate.Poetry`
- `isolate.environments.Conda` -> `environments.isolate.Conda`
**2023**
- `other.purposes.DevOps / systems administration / writing automation scripts` -> `other.purposes.DevOps / System administration / Writing automation scripts`
- `other.purposes.Multimedia applications development (apps handling various types of multimedia content, e_g_ audio, graphics, etc_)` -> `other.purposes.Multimedia applications development`
- `how.involved.DevOps / systems administration / writing automation scripts` -> `how.involved.DevOps / System administration / Writing automation scripts`
- `how.involved.Multimedia applications development (apps handling various types of multimedia content, e.g. audio, graphics, etc.)` -> `how.involved.Multimedia applications development`
- `how.involved.Other, please specify:` -> `how.involved.Other, please specify`
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`
- `python.version.upgrade.OS-wide package-management tool (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-wide package-management tool`
- `run.in.cloud.On a platform-as-a-service (such as Heroku or Google App Engine)` -> `run.in.cloud.On a platform-as-a-service`
**2024**
- `other.purposes.DevOps / systems administration / writing automation scripts` -> `other.purposes.DevOps / System administration / Writing automation scripts`
- `other.purposes.Multimedia applications development (apps handling various types of multimedia content, e_g_ audio, graphics, etc_)` -> `other.purposes.Multimedia applications development`
- `how.involved.DevOps / systems administration / writing automation scripts` -> `how.involved.DevOps / System administration / Writing automation scripts`
- `how.involved.Multimedia applications development (apps handling various types of multimedia content, e.g. audio, graphics, etc.)` -> `how.involved.Multimedia applications development`
- `how.involved.Other, please specify:` -> `how.involved.Other, please specify`
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`
- `python.version.upgrade.OS-wide package-management tool (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-wide package-management tool`
- `python.version.why.The version I’m using meets all my needs` -> `python.version.why.The version I'm using meets all my needs`
