# Git 从零到一完整教程

> 面向 CaosBioGuard 项目，但也适用于任何 Git 仓库。
> 本教程用 `origin` 表示远程名（Git 通用惯例）；**本仓库实际远程名是 `main`**，使用时把 `origin` 换成 `main` 即可（详见第十五部分）。

---

## 目录

1. [核心概念](#一核心概念先理解再动手)
2. [安装与配置](#二安装与配置)
3. [创建仓库与克隆](#三创建仓库与克隆)
4. [日常工作流：提交·推送·拉取](#四日常工作流提交推送拉取)
5. [分支管理](#五分支管理)
6. [撤回与撤销](#六撤回与撤销)
7. [合并冲突解决](#七合并冲突解决)
8. [变基 rebase](#八变基-rebase)
9. [暂存 stash](#九暂存-stash)
10. [标签 tag](#十标签-tag)
11. [历史重写](#十一历史重写)
12. [远程与协作](#十二远程与协作)
13. [查看历史与排查](#十三查看历史与排查)
14. [安全网：找回丢失的提交](#十四安全网找回丢失的提交)
15. [本仓库注意事项](#十五本仓库注意事项)
16. [速查表](#十六速查表)

---

## 一、核心概念（先理解再动手）

### 1.1 Git 是什么

Git 是**分布式版本控制系统**：它把项目文件的每一次改动都拍成「快照」存下来，
你可以随时回到任意历史状态、创建并行分支、多人协作，且每个副本都完整。

### 1.2 三个区域（最重要）

你的改动在 Git 里经历三个区域：

```
工作区                暂存区                本地仓库              远端
(磁盘上的文件)  ──git add──▶  (待提交清单)  ──git commit──▶  (提交历史)  ──git push──▶  (GitHub)
    ▲                        ▲                     ▲
    └──── git restore        └── git restore --staged
```

- **工作区（Working Directory）**：你磁盘上实际看到的文件。
- **暂存区（Index / Staging Area）**：`git add` 放进去的「准备提交」的改动。
- **本地仓库（Repository）**：`git commit` 后形成的永久历史快照。
- **远端（Remote）**：GitHub 上的仓库。

> 记住这张图，后面所有「撤回」都是围绕它展开的。

### 1.3 提交（commit）与快照

每次 `git commit` 会保存**整个项目的快照**（内容没变的文件用指针复用，不重复存），
并生成一个唯一的 SHA-1 哈希 ID，例如 `0316c1a`。这个 ID 就是提交的「身份证」。

### 1.4 HEAD 与分支指针

- **HEAD**：指向你「当前所在的位置」，通常是一个分支。
- **分支（branch）**：本质只是一个**指向某个 commit 的可移动指针**。创建分支极轻量，就是新建一个指针。

```
                        HEAD
                          │
main ──▶ 0316c1a ◀── 68d0ed1 ◀── a59eac2 ◀── 4b0607d
```

上图：`main` 和 `dev` 都指向 `0316c1a`，HEAD 指向 `main`。

### 1.5 为什么需要分支

让你在不影响主线的同时并行开发、实验、修复。完成后合并回主线即可。

---

## 二、安装与配置

### 2.1 验证安装

```bash
git --version        # 输出版本号即已安装
```

### 2.2 配置身份（每个提交都会带上它）

```bash
git config --global user.name  "你的名字"
git config --global user.email "你的邮箱"
```

> `--global` 表示全局（对所有仓库生效）；去掉则只对当前仓库生效。

### 2.3 换行符（Windows 推荐）

```bash
git config --global core.autocrlf true
```

Windows 用 `CRLF`、Linux/Mac 用 `LF`，这个配置让 Git 自动转换，避免跨平台冲突。

### 2.4 查看配置

```bash
git config --list              # 列出所有配置
git config user.email          # 查某一项
```

### 2.5 GPG 提交签名（本仓库已配置）

详见第五节「GPG 提交签名」。

---

## 三、创建仓库与克隆

### 3.1 从零新建仓库

```bash
cd 你的项目目录
git init                       # 初始化，生成 .git 目录
git add .
git commit -m "init: 初始化项目"
git remote add origin <仓库地址>
git push -u origin main        # 首次推送并建立跟踪
```

### 3.2 克隆已有仓库

```bash
git clone <仓库地址>            # 克隆到当前目录下的同名文件夹
git clone <仓库地址> 自定义名字  # 克隆到指定目录
```

克隆后会自动有一个叫 `origin` 的远程、一个默认分支，并建立跟踪关系。

### 3.3 查看状态

```bash
git status                     # 完整状态
git status --short             # 精简版（每文件一行）
```

---

## 四、日常工作流（提交·推送·拉取）

### 4.1 完整提交流程

```bash
git status                     # 1. 看改了什么
git add <file>                 # 2. 暂存要提交的文件（按文件名加，避免误加敏感文件）
git status                     # 3. 确认暂存区内容
git commit -m "描述"           # 4. 提交
git push                       # 5. 推送到跟踪的远端分支
```

常用 add 变体：

```bash
git add <file1> <file2>        # 暂存指定文件
git add <目录>/                 # 暂存整个目录
git add -A                     # 暂存所有改动（含删除、新增）
git add .                      # 暂存当前目录所有改动
```

> 只改「已跟踪文件」时，可一步完成：`git commit -am "描述"`（自动 add + commit）。

### 4.2 提交信息规范（建议）

用「类型: 说明」的前缀，一眼看出改动性质：

```
feat:   新功能
fix:    修复 bug
docs:   文档
chore:  杂项（如配置、依赖）
refactor: 重构（不改变行为）
test:   测试
```

本仓库已有 `chore:`、`docs:` 这类提交，保持一致即可。

### 4.3 推送

```bash
git push                        # 推到当前分支跟踪的远端
git push <远程> <分支>           # 指定远程和分支
git push -u <远程> <分支>        # 首次推送，并记住跟踪关系（之后可省略参数）
git push <远程> <本地>:<远端>    # 跨分支推送（如把 main 推到 dev/0.1.3）
```

### 4.4 拉取 / 更新

```bash
git fetch                       # 只下载远端更新，不改本地代码（安全）
git pull                        # 下载 + 合并（merge）
git pull --rebase               # 下载 + rebase（线性历史，推荐）
git fetch --prune               # 下载并清理已删除的远端分支
```

> 建议习惯：先 `git fetch` 看变化，再决定 `pull` 还是 `rebase`。

### 4.5 .gitignore

列出「不想被 Git 追踪」的文件/目录，一行一个：

```
config.ini          # 忽略指定文件
sideUI/dd/          # 忽略整个目录
*.db                # 通配符忽略某类文件
```

> 注意：`.gitignore` 只对**尚未被追踪**的文件生效；已追踪的文件要先 `git rm --cached` 移出（见第十一部分）。

---

## 五、分支管理

### 5.1 查看分支

```bash
git branch                      # 列出本地分支
git branch -a                   # 列出所有（含远端）
git branch -a -vv               # 分支 + 跟踪关系 + 领先/落后
```

### 5.2 创建 / 切换分支

```bash
git branch <name>               # 新建分支（不切换）
git checkout <name>             # 切换分支
git checkout -b <name>          # 新建并切换
git switch -c <name>            # 同上（Git 2.23+ 新语法，更推荐）
```

### 5.3 删除分支

```bash
git branch -d <name>            # 删除已合并的本地分支
git branch -D <name>            # 强制删除本地分支（即使未合并）
```

### 5.4 合并分支（merge）

把 `dev` 的改动合并到当前所在分支：

```bash
git checkout main               # 先切到目标分支
git merge dev                   # 把 dev 合并进 main
```

- 若 `main` 在 `dev` 之后没有新提交 → **快进（fast-forward）**，指针直接前移，无新提交。
- 若两边都有新提交 → 产生一个 **merge 提交**（有两个父提交）。

### 5.5 本仓库的分支策略

- `main`：稳定主分支，日常开发在这里。
- `dev/0.1.x`：偶尔存档开发版（用分支或 tag 均可）。

```bash
# 存档开发版
git checkout -b dev/0.1.4       # 从当前 main 建一个 dev 存档分支
git push -u main dev/0.1.4      # 推到远端
git checkout main               # 立即切回 main
```

---

## 六、撤回与撤销

### 6.1 按「改动在哪一阶段」选命令

| 场景 | 命令 | 说明 |
|---|---|---|
| 丢弃某文件的未暂存改动 | `git restore <file>` | 改动直接丢失，不可恢复 |
| 丢弃所有未暂存改动 | `git restore .` | 同上，谨慎 |
| 取消暂存（unstage） | `git restore --staged <file>` | 改动回到工作区，不丢失 |
| 撤回最后一次提交，改动回暂存区 | `git reset --soft HEAD~1` | 提交没了，改动还在 |
| 撤回最后一次提交，改动回工作区 | `git reset HEAD~1` | 默认 --mixed |
| 撤回最后一次提交，彻底丢弃 | `git reset --hard HEAD~1` | 提交和改动全没，危险 |
| 修改最后一次提交 | `git commit --amend` | 补文件或改信息 |
| 撤回已推送的提交（安全） | `git revert <commit>` | 生成反向提交，不改历史 |
| 撤回已推送的提交（危险） | `git reset --hard <commit>` 后 `git push --force` | 改写历史，影响协作者 |

### 6.2 reset 三种模式详解

`git reset` 移动「当前分支指针」，区别在于**工作区和暂存区是否保留**：

| 模式 | 指针 | 暂存区 | 工作区 | 用途 |
|---|---|---|---|---|
| `--soft` | 回退 | 保留 | 保留 | 只想撤销提交、保留所有改动 |
| `--mixed`（默认） | 回退 | 清空 | 保留 | 撤销提交和暂存，改动留工作区 |
| `--hard` | 回退 | 清空 | 清空 | 彻底回到某状态，丢弃一切 |

> 口诀：`--soft` 留到暂存区；`--mixed` 留到工作区；`--hard` 全丢。

### 6.3 revert vs reset

- **revert**：生成一个「反向提交」抵消目标提交，历史完整保留 → **适合已推送的**。
- **reset**：把指针往回挪，历史被改写 → **只适合没推送的本地提交**。

```bash
git revert 0316c1a              # 生成新提交，抵消 0316c1a 的改动
git reset --hard 68d0ed1        # 指针直接回到 68d0ed1，之后的提交消失
```

### 6.4 修改最后一次提交

```bash
git add 漏掉的文件
git commit --amend             # 把漏掉的文件补进上次提交
git commit --amend -m "新信息" # 只改提交信息
```

> `--amend` 会改写提交 ID；若已推送，需要 `git push --force`。

---

## 七、合并冲突解决

### 7.1 冲突是怎么产生的

两个分支**改了同一文件的同一处**，Git 无法判断保留哪个，就报冲突让你手动决定。

### 7.2 识别冲突

```bash
git merge dev
# 输出：CONFLICT (content): Merge conflict in <file>
git status
# 显示：both modified: <file>
```

### 7.3 冲突标记含义

冲突文件里会出现：

```
<<<<<<< HEAD
这里是当前分支（main）的内容
=======
这里是要合并进来（dev）的内容
>>>>>>> dev
```

### 7.4 解决步骤

1. 打开冲突文件，找到 `<<<<<<<` / `=======` / `>>>>>>>` 标记；
2. 手动编辑，**保留你想要的内容，删除标记本身**；
3. 保存文件；
4. 标记为已解决：
   ```bash
   git add <file>
   ```
5. 完成合并：
   ```bash
   git commit          # 不带 -m，会弹出编辑器显示默认合并信息
   # 或
   git commit -m "merge: 合并 dev 解决冲突"
   ```

### 7.5 中止合并（放弃本次合并）

```bash
git merge --abort              # 回到合并前的状态
```

### 7.6 减少冲突的建议

- 提交前先 `git pull --rebase`，保持和远端同步；
- 小而频繁地提交、合并，避免大跨度合并。

---

## 八、变基 rebase

### 8.1 rebase 与 merge 的区别

- **merge**：把两个分支「并」起来，产生一个 merge 提交，历史呈分叉状。
- **rebase**：把当前分支的提交「搬到」目标分支顶端，历史呈**一条直线**。

```
merge 结果：            rebase 结果：
  * merge commit           main ─▶ * c'
  |\                              │
  | * dev                        * b'
  * main  *                       │
  |/                              * a'
  * base                     base ─▶ *
```

### 8.2 基本 rebase

```bash
git checkout dev
git rebase main               # 把 dev 的提交搬到 main 顶端
```

结果：dev 的历史变成「基于最新 main」的线性历史。

### 8.3 交互式 rebase（整理历史）

```bash
git rebase -i HEAD~3          # 整理最近 3 个提交
git rebase -i <commit>        # 整理该 commit 之后的所有提交
```

会弹出编辑器，每个提交一行，可修改前面的命令词：

| 命令 | 含义 |
|---|---|
| `pick` | 保留该提交（默认） |
| `reword` | 保留，但修改提交信息 |
| `edit` | 保留，但停下来让你改内容 |
| `squash` | 合并到上一个提交（保留信息） |
| `fixup` | 合并到上一个提交（丢弃信息） |
| `drop` | 删除该提交 |

### 8.4 常见场景

**把多个小提交压成一个：**

```bash
git rebase -i HEAD~3
# 把后两行的 pick 改成 squash（或 fixup），保存退出
```

**修改历史提交信息：**

```bash
git rebase -i HEAD~3
# 把目标行的 pick 改成 reword，保存后逐个修改信息
```

### 8.5 黄金法则（务必记住）

> **绝不要 rebase 已经推送到公共仓库、可能被别人拉取的分支。**

rebase 会改写提交 ID，别人基于旧历史的工作会乱套。只在「自己的、未推送的」分支上 rebase。

---

## 九、暂存 stash

「我改到一半，需要临时切去别的分支处理，又不想现在提交」时用：

```bash
git stash                       # 暂存当前改动（工作区变干净）
git stash list                  # 查看暂存列表
git stash pop                   # 恢复最近一次暂存（并从列表移除）
git stash apply                 # 恢复但不移除
git stash drop                  # 删除最近一次暂存
git stash save "说明"           # 暂存并加说明
```

---

## 十、标签 tag

标记重要节点（如发布版本），是「只读快照」。

### 10.1 创建标签

```bash
git tag v1.0.0                          # 轻量标签（只是个指针）
git tag -a v1.0.0 -m "版本说明"          # 附注标签（含作者、时间、说明，推荐）
git tag -a v1.0.0 <commit> -m "..."     # 给历史某提交打标签
```

### 10.2 查看 / 推送 / 删除

```bash
git tag                         # 列出所有标签
git show v1.0.0                 # 查看标签详情

git push origin v1.0.0          # 推送单个标签
git push origin --tags          # 推送所有标签

git tag -d v1.0.0               # 删除本地标签
git push origin :refs/tags/v1.0.0   # 删除远端标签
```

---

## 十一、历史重写

### 11.1 修改最后一次提交

```bash
git commit --amend              # 见 6.4
```

### 11.2 用 rebase -i 改写历史

见 8.3，可 squash、reword、drop 历史提交。

### 11.3 停止追踪文件（保留本地文件）

处理「运行时自动生成」的文件（如 `records.db`），只影响「以后」，不碰历史：

```bash
git ls-files | grep '\.db$'            # 找出被追踪的 db 文件
git rm --cached sideUI/dd/records.db   # 移出追踪（--cached 只移索引，不删本地文件）
git status --short                     # 看到 D  sideUI/dd/records.db（本地文件仍在）
git commit -m "chore: 停止追踪 records.db"
git push

# 验证
git ls-files sideUI/dd/                # 空 = 已不再追踪
git check-ignore -v sideUI/dd/records.db   # 命中 .gitignore = 以后自动忽略
```

### 11.4 彻底从历史删除文件（filter-repo）

用于把某个文件从**所有历史提交**中删除（如泄露的 `config.ini`）。
思路：**镜像克隆 → 重写 → 强推**，全程不污染工作目录。

```bash
# 0) 安装工具（只需一次）
python -m pip install git-filter-repo
git filter-repo --version

# 1) 镜像克隆（bare，含全部分支+标签）
git clone --mirror git@github.com:mxwz/CaosBioGuard.git _clean_mirror.git

# 2) 进入镜像，查看现状
cd _clean_mirror.git
git remote -v                      # 确认远程名是 origin
git show-ref                       # 查看所有分支 / 标签 / PR ref

# 3) 核心：从所有历史删除 config.ini
git filter-repo --path config.ini --invert-paths
#   --path config.ini : 目标文件
#   --invert-paths    : 反选，即「删除该路径」而非「只保留该路径」

# 4) 验证删干净
git rev-list --all --objects | grep config.ini   # 无输出 = 已清除
git log --all --oneline -- config.ini            # 无输出 = 已清除

# 5) 删除 GitHub 的 PR ref（只读引用，会阻碍 --mirror 推送）
git update-ref -d refs/pull/2/head
git update-ref -d refs/pull/3/head

# 6) 强推覆盖远端（破坏性，重写 GitHub 历史）
git push --mirror git@github.com:mxwz/CaosBioGuard.git
```

> `--mirror` 会把远端所有 ref 覆盖成本地镜像的样子（含删除远端不再存在的分支）。
> 执行前务必确认要清理的东西已吊销（如旧密钥）。

### 11.5 同步本地工作仓库（强推之后）

强推后本地分支还指向旧历史，需拉新历史并重置：

```powershell
# 1) 备份敏感文件（reset --hard 会把它从工作区删掉）
Copy-Item config.ini "$env:TEMP\config.ini.bak"

# 2) 拉取新历史
git fetch main --prune --tags --force

# 3) 看分叉情况
git branch -a -vv
git log --graph --oneline --all

# 4) 重置本地分支到新历史
git reset --hard main/dev/0.1.3
git branch -f main refs/remotes/main/main

# 5) 恢复备份
Copy-Item "$env:TEMP\config.ini.bak" config.ini

# 6) 清理本地残留旧对象
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 7) 最终验证
git rev-list --all --objects | grep config.ini   # 空 = 干净
git check-ignore -v config.ini
```

---

## 12. 远程与协作

### 12.1 查看 / 管理远程

```bash
git remote -v                    # 查看远程地址
git remote add origin <地址>      # 添加远程
git remote remove origin         # 删除远程
git remote rename origin main    # 重命名远程
```

### 12.2 fetch / pull / push 的区别

| 命令 | 作用 | 改本地吗 |
|---|---|---|
| `git fetch` | 只下载远端更新到本地引用 | 不改工作区 |
| `git pull` | fetch + merge | 改 |
| `git push` | 把本地提交上传到远端 | 不改本地 |

### 12.3 远程分支与跟踪关系

```bash
git branch -a -vv                # 看本地分支跟踪哪个远端分支
git push -u origin <分支>         # 首次推送并建立跟踪
git branch --set-upstream-to=origin/<分支>   # 手动设置跟踪
```

### 12.4 删除远程分支

```bash
git push origin --delete <分支>   # 删除远端分支
git push origin :<分支>           # 旧式写法，等价
```

---

## 十三、查看历史与排查

### 13.1 log

```bash
git log                              # 完整日志
git log --oneline                    # 每条一行
git log --oneline --graph --all      # 提交图（最直观）
git log --oneline -10                # 最近 10 条
git log --all --oneline -- <file>    # 某文件的历史
git log -p <file>                    # 某文件的逐次改动
git log --author="名字"              # 按作者筛选
```

### 13.2 diff

```bash
git diff                       # 工作区 vs 暂存区（未暂存的改动）
git diff --staged              # 暂存区 vs 上次提交（已暂存的改动）
git diff <commit1> <commit2>   # 两个提交之间的差异
git diff <file>                # 某文件的改动
git diff --stat                # 只看改了哪些文件、多少行
```

### 13.3 show / blame

```bash
git show <commit>              # 查看某提交的完整内容
git show <commit>:<file>       # 查看某提交时某文件的内容
git blame <file>               # 逐行看「谁在哪个提交改的」
```

---

## 十四、安全网（找回丢失的提交）

### 14.1 reflog（救命稻草）

`git reflog` 记录 HEAD 的**所有移动**（包括被 reset、rebase、amend 掉的历史），
即使 `reset --hard` 误删了提交，也能找回：

```bash
git reflog                     # 列出 HEAD 的移动历史
git reflog <分支>              # 某分支的移动历史
# 找到目标提交 ID 后恢复：
git reset --hard <丢失的commit>
git checkout -b 恢复分支 <丢失的commit>
```

> 只要没执行过 `git gc`，几乎任何「丢失」的提交都能用 reflog 找回。

### 14.2 清理与回收

```bash
git reflog expire --expire=now --all   # 立即过期所有 reflog（清历史残留）
git gc --prune=now --aggressive        # 垃圾回收，物理删除无引用的对象
```

---

## 十五、本仓库注意事项

1. **远程名叫 `main`，不是 `origin`**：本仓库 `git remote -v` 显示远程名是 `main`，
   所以拉取用 `git fetch main`，远端引用形如 `main/main`、`main/dev/0.1.3`。
   本教程里所有 `origin` 都要换成 `main`。

2. **本地分支 `main` 与远程 `main` 同名**：个别命令会提示
   `refname 'main' is ambiguous`。歧义时用完整引用消歧：
   - 远端：`refs/remotes/main/main`
   - 本地：`refs/heads/main`

3. **GPG 提交签名已开启**：每次 `git commit` 会自动签名，配置见下：

   ```bash
   git config gpg.program "F:/GnuPG/bin/gpg.exe"
   git config user.signingkey FD3B17135D9F9A5A
   git config commit.gpgsign true
   git config user.email "hakanyang@qq.com"   # 必须与 GPG UID 一致，GitHub 才显示 Verified
   ```

4. **敏感文件绝不能提交**：`config.ini`、`web_admin/.env` 含密钥/密码，已在 `.gitignore` 中。
   提交前务必 `git status` 确认没有误加敏感文件。

---

## 十六、速查表

### 提交 / 推送 / 拉取

```bash
git status                              # 看状态
git add <file>                          # 暂存
git commit -m "描述"                    # 提交
git commit -am "描述"                   # 暂存+提交（已跟踪文件）
git push                                # 推送到跟踪远端
git push -u origin <分支>               # 首次推送
git pull --rebase                       # 拉取并变基
git fetch                               # 只下载
```

### 分支 / 标签

```bash
git branch                              # 列出本地分支
git branch -a -vv                       # 所有分支+跟踪
git checkout -b <name>                  # 新建并切换
git switch -c <name>                    # 新建并切换（新语法）
git merge <branch>                      # 合并
git rebase <branch>                     # 变基
git branch -d <name>                    # 删除本地分支
git tag -a v1.0.0 -m "说明"             # 打附注标签
git push origin --tags                  # 推送标签
```

### 撤回

```bash
git restore <file>                      # 丢弃未暂存改动
git restore --staged <file>             # 取消暂存
git reset --soft HEAD~1                 # 撤提交，改动留暂存区
git reset HEAD~1                        # 撤提交，改动留工作区
git reset --hard HEAD~1                 # 撤提交，改动全丢
git commit --amend                      # 改最后一次提交
git revert <commit>                     # 安全撤回已推送提交
```

### 查看 / 排查

```bash
git log --oneline --graph --all         # 提交图
git log --all --oneline -- <file>       # 某文件历史
git diff                                # 未暂存改动
git diff --staged                       # 已暂存改动
git show <commit>                       # 查看提交
git blame <file>                        # 逐行溯源
git reflog                              # 找回丢失的提交
```

### 历史重写（进阶）

```bash
git rm --cached <file>                  # 停止追踪（保留本地文件）
git filter-repo --path <file> --invert-paths   # 从所有历史删除文件
git rebase -i HEAD~N                    # 交互式整理最近 N 个提交
```
