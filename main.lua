--[[
    MM2 AUTO FARM - ym1co farmer 5.0 (Syntax Fix & Renamed)
    Developed by: ym1co
--]]

-- Anti-duplicate execution guard
if getgenv().YM1CO_LOADED then
    if getgenv().YM1CO_NOTIFY then
        getgenv().YM1CO_NOTIFY("ym1co farmer 5.0", "Script is already running", 3)
    end
    return
end
getgenv().YM1CO_LOADED = true

-- Roblox Services
local Players = game:GetService("Players")
local Workspace = game:GetService("Workspace")
local RunService = game:GetService("RunService")
local TweenService = game:GetService("TweenService")
local VirtualUser = game:GetService("VirtualUser")
local HttpService = game:GetService("HttpService")
local TeleportService = game:GetService("TeleportService")
local CoreGui = game:GetService("CoreGui")
local UserInputService = game:GetService("UserInputService")
local Lighting = game:GetService("Lighting")
local GuiService = game:GetService("GuiService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local StarterGui = game:GetService("StarterGui")

local LocalPlayer = Players.LocalPlayer

local isGameExiting = false
local lastKnownLevel = 0
local lastKnownCoins = 0
local sessionCoinsFarmed = 0

-- ==================== ДЕТЕКТ КИКА / ДИСКОННЕКТА -> ВЫХОД И ПЕРЕЗАПУСК ДЛЯ SOLARA ====================
local function initDisconnectHandler()
    local function triggerExit(reason)
        if isGameExiting then return end
        isGameExiting = true
        warn("[DisconnectHandler] Kick/disconnect detected: " .. tostring(reason) .. ". Exiting for clean Solara launch...")

        -- Записываем статус KICKED_OR_DISCONNECTED в файл статистики
        pcall(function()
            if writefile then
                local kickData = {
                    username = LocalPlayer.Name,
                    userId = LocalPlayer.UserId,
                    status = "KICKED_OR_DISCONNECTED",
                    level = lastKnownLevel or 0,
                    coins = lastKnownCoins or sessionCoinsFarmed or 0,
                    error = tostring(reason),
                    updatedAt = os.time(),
                    timestamp = os.date("%Y-%m-%d %H:%M:%S")
                }
                writefile("stats_" .. tostring(LocalPlayer.UserId) .. ".json", HttpService:JSONEncode(kickData))
            end
        end)

        task.wait(0.2)

        -- Закрываем клиент Roblox, чтобы farm_manager перезапустил чистый процесс под Solara
        pcall(function()
            game:Shutdown()
        end)

        -- Если процесс не закрылся сразу, пробуем кликнуть кнопку закрытия/выхода
        task.wait(1.0)
        pcall(function()
            local promptGui = CoreGui:FindFirstChild("RobloxPromptGui")
            local overlay = promptGui and promptGui:FindFirstChild("promptOverlay")
            local prompt = overlay and overlay:FindFirstChild("ErrorPrompt")
            if prompt then
                local btn = prompt:FindFirstChild("ButtonDefault", true) or prompt:FindFirstChild("ButtonPrimary", true) or prompt:FindFirstChild("ConfirmButton", true)
                if btn then
                    if firesignal and btn:FindFirstChild("Activated") then
                        firesignal(btn.Activated)
                    elseif getconnections then
                        for _, conn in ipairs(getconnections(btn.MouseButton1Click or btn.Activated)) do
                            conn:Fire()
                        end
                    end
                end
            end
        end)

        task.wait(0.5)
        pcall(function()
            game:Shutdown()
        end)
    end

    pcall(function()
        GuiService.ErrorMessageChanged:Connect(function(msg)
            if msg and msg ~= "" then
                triggerExit("ErrorMessageChanged: " .. tostring(msg))
            else
                local errCode = GuiService:GetErrorCode()
                if errCode and errCode ~= Enum.ConnectionError.OK then
                    triggerExit("ErrorCode: " .. tostring(errCode))
                end
            end
        end)
    end)

    task.spawn(function()
        pcall(function()
            local promptGui = CoreGui:WaitForChild("RobloxPromptGui", 10)
            local overlay = promptGui and promptGui:WaitForChild("promptOverlay", 10)
            if overlay then
                overlay.ChildAdded:Connect(function(child)
                    if child.Name == "ErrorPrompt" then
                        task.wait(0.2)
                        local msg = "ErrorPrompt appeared"
                        pcall(function()
                            local errLabel = child:FindFirstChild("ErrorMessage", true)
                            if errLabel and errLabel:IsA("TextLabel") and errLabel.Text ~= "" then
                                msg = errLabel.Text
                            end
                        end)
                        triggerExit(msg)
                    end
                end)
                if overlay:FindFirstChild("ErrorPrompt") then
                    triggerExit("ErrorPrompt already active")
                end
            end
        end)
    end)
end

task.spawn(initDisconnectHandler)

-- Авто-сохранение скрипта при любых телепортациях / сменах серверов
pcall(function()
    local qot = (syn and syn.queue_on_teleport) or queue_on_teleport or (fluxus and fluxus.queue_on_teleport)
    if qot then
        qot('loadstring(game:HttpGet("https://raw.githubusercontent.com/surf1k/ym1co-farmer/main/main.lua"))()')
    end
end)

repeat task.wait() until game:IsLoaded()

local scriptLoadTime = tick()

-- ==================== МАКСИМАЛЬНАЯ ОПТИМИЗАЦИЯ ОЗУ И GPU (EXTRA RAM) ====================
local function applyExtremeOptimization()
    -- 1. Отключение 3D рендеринга (снижает нагрузку на GPU и ОЗУ практически до нуля)
    pcall(function()
        RunService:Set3dRenderingEnabled(false)
    end)

    -- 2. Ограничение FPS (15 FPS достаточно для автофарма)
    pcall(function()
        if setfpscap then
            setfpscap(15)
        end
    end)

    -- 3. Минимальный уровень графики
    pcall(function()
        settings().Rendering.QualityLevel = 1
        settings().Rendering.EditQualityLevel = 1
    end)

    -- 4. Очистка глобального освещения, теней, атмосферы и неба
    pcall(function()
        Lighting.GlobalShadows = false
        Lighting.FogEnd = 9e9
        Lighting.Brightness = 0
        Lighting.ClockTime = 14

        for _, v in ipairs(Lighting:GetChildren()) do
            if v:IsA("PostProcessEffect") or v:IsA("Atmosphere") or v:IsA("Sky") or v:IsA("Clouds") then
                v.Enabled = false
            end
        end
    end)

    -- 5. Очистка текстур, декалей, звуков, частиц со всех игровых объектов
    pcall(function()
        for _, v in ipairs(game:GetDescendants()) do
            if v:IsA("Decal") or v:IsA("Texture") then
                v.Transparency = 1
            elseif v:IsA("ParticleEmitter") or v:IsA("Trail") or v:IsA("Smoke") or v:IsA("Fire") or v:IsA("Explosion") or v:IsA("Sparkles") or v:IsA("Highlight") then
                v.Enabled = false
            elseif v:IsA("Sound") then
                v.Volume = 0
                v:Stop()
            elseif v:IsA("BasePart") and not v:IsA("MeshPart") then
                v.Material = Enum.Material.SmoothPlastic
                v.Reflectance = 0
                v.CastShadow = false
            end
        end
    end)

    -- 6. Авто-очистка для динамически спавнящихся ассетов (новые карты, скины, эффекты)
    pcall(function()
        if not getgenv()._mm2_extra_ram_hook then
            getgenv()._mm2_extra_ram_hook = Workspace.DescendantAdded:Connect(function(v)
                if not Settings or not Settings.ExtremeRAMSaver then return end
                pcall(function()
                    if v:IsA("Decal") or v:IsA("Texture") then
                        v.Transparency = 1
                    elseif v:IsA("ParticleEmitter") or v:IsA("Trail") or v:IsA("Smoke") or v:IsA("Fire") or v:IsA("Explosion") or v:IsA("Sparkles") or v:IsA("Highlight") then
                        v.Enabled = false
                    elseif v:IsA("Sound") then
                        v.Volume = 0
                        v:Stop()
                    elseif v:IsA("BasePart") and not v:IsA("MeshPart") then
                        v.Material = Enum.Material.SmoothPlastic
                        v.Reflectance = 0
                        v.CastShadow = false
                    end
                end)
            end)
        end
    end)
end

-- Включаем Extra RAM сразу при старте
applyExtremeOptimization()


-- Load Rayfield UI Library
local Rayfield = nil
local rayfield_urls = {
    "https://raw.githubusercontent.com/SiriusSoftwareLtd/Rayfield/main/source.lua",
    "https://sirius.menu/rayfield"
}
for _, u in ipairs(rayfield_urls) do
    local ok, res = pcall(function()
        return loadstring(game:HttpGet(u))()
    end)
    if ok and res then
        Rayfield = res
        break
    end
end

-- ==================== НЕОНОВО-ЗЕЛЁНАЯ ТЕМА RAYFIELD ====================
local GreenTheme = {
    TextColor = Color3.fromRGB(220, 240, 215),
    Background = Color3.fromRGB(12, 20, 14),
    Topbar = Color3.fromRGB(20, 34, 24),
    Shadow = Color3.fromRGB(6, 12, 8),
    NotificationBackground = Color3.fromRGB(16, 28, 20),
    NotificationActionsBackground = Color3.fromRGB(26, 44, 30),
    TabBackground = Color3.fromRGB(16, 28, 20),
    TabStroke = Color3.fromRGB(120, 196, 93),
    TabBackgroundSelected = Color3.fromRGB(28, 52, 34),
    TabTextColor = Color3.fromRGB(180, 220, 175),
    SelectedTabTextColor = Color3.fromRGB(120, 196, 93),
    ElementBackground = Color3.fromRGB(16, 26, 19),
    ElementBackgroundHover = Color3.fromRGB(24, 40, 28),
    SecondaryElementBackground = Color3.fromRGB(12, 20, 14),
    ElementStroke = Color3.fromRGB(120, 196, 93),
    SecondaryElementStroke = Color3.fromRGB(78, 110, 68),
    SliderBackground = Color3.fromRGB(20, 34, 24),
    SliderProgress = Color3.fromRGB(120, 196, 93),
    SliderStroke = Color3.fromRGB(222, 192, 126),
    ToggleBackground = Color3.fromRGB(18, 30, 22),
    ToggleEnabled = Color3.fromRGB(120, 196, 93),
    ToggleDisabled = Color3.fromRGB(45, 60, 50),
    ToggleEnabledStroke = Color3.fromRGB(120, 196, 93),
    ToggleDisabledStroke = Color3.fromRGB(65, 85, 70),
    ToggleEnabledOuterStroke = Color3.fromRGB(80, 140, 65),
    ToggleDisabledOuterStroke = Color3.fromRGB(40, 55, 45),
    DropdownSelected = Color3.fromRGB(28, 52, 34),
    DropdownUnselected = Color3.fromRGB(16, 26, 19),
    InputBackground = Color3.fromRGB(14, 24, 17),
    InputStroke = Color3.fromRGB(120, 196, 93),
    PlaceholderColor = Color3.fromRGB(110, 150, 115)
}

local Window = nil
if Rayfield then
    pcall(function()
        if Rayfield.Theme then
            Rayfield.Theme["Green"] = GreenTheme
            Rayfield.Theme["Default"] = GreenTheme
        end
        if Rayfield.Themes then
            Rayfield.Themes["Green"] = GreenTheme
            Rayfield.Themes["Default"] = GreenTheme
        end
    end)
    Window = Rayfield:CreateWindow({
        Name = "ym1co farmer 5.0",
        Icon = 0,
        LoadingTitle = "ym1co farmer 5.0",
        LoadingSubtitle = "Steampunk Emerald Edition",
        Theme = "Green",
        DisableRayfieldPrompts = false,
        DisableBuildWarnings = true,
        ConfigurationSaving = {
            Enabled = true,
            FolderName = "ym1co_farmer_v5",
            FileName = "config"
        },
        KeySystem = false
    })
    if Rayfield.ChangeTheme then
        pcall(function() Rayfield:ChangeTheme("Green") end)
    end
end

local function notifyUser(title, content, duration)
    if Rayfield and Window then
        Rayfield:Notify({
            Title = title,
            Content = content,
            Duration = duration or 3,
            Image = 0
        })
    else
        print(string.format("[%s] %s", tostring(title), tostring(content)))
    end
end

-- ==================== НАСТРОЙКИ ПО УМОЛЧАНИЮ ====================
local Settings = {
    AutoFarm = true,
    FarmSpeed = 22,
    FarmMode = "Tween",
    CoinDelay = 0.01,
    MaxBagCapacity = 40,
    ActionOnFull = "CombatWin",

    AvoidMurderer = true,
    AvoidDistance = 35,
    AvoidAction = "Kite",
    AutoGrabGun = false,
    GunPriority = false,

    AutoWinAsRoles = false,

    AutoHopAfterRound = false,
    HopPlayerThreshold = 22,

    ShowHUD = false,
    ESP_Murderer = true,
    ESP_Sheriff = true,
    ESP_Innocents = false,

    Noclip = true,
    WalkSpeed = 16,
    JumpPower = 50,
    InfJump = false,

    FPSBooster = true,
    AntiAFK = true,
    ExtremeRAMSaver = true,
    AutoServerHopOnBotCollision = true,
    AutoHopLowPlayerCount = true,
    MinPlayersInServer = 4,
    BotUsernamePrefix = "Fmr_",

    AutoExportStats = true,
    ExportInterval = 5,
    CustomLogFileName = "mm2_farm_stats.txt"
}

-- Anti-AFK
LocalPlayer.Idled:Connect(function()
    if Settings.AntiAFK then
        VirtualUser:Button2Down(Vector2.new(0, 0), Workspace.CurrentCamera.CFrame)
        task.wait(1)
        VirtualUser:Button2Up(Vector2.new(0, 0), Workspace.CurrentCamera.CFrame)
    end
end)

-- Легковесный Noclip
local noclipConnection = nil
local function toggleNoclip(state)
    Settings.Noclip = state
    if state then
        if not noclipConnection then
            noclipConnection = RunService.Stepped:Connect(function()
                local char = LocalPlayer.Character
                if char then
                    local root = char:FindFirstChild("HumanoidRootPart")
                    local head = char:FindFirstChild("Head")
                    local torso = char:FindFirstChild("Torso") or char:FindFirstChild("UpperTorso")
                    local lowerTorso = char:FindFirstChild("LowerTorso")
                    if root then root.CanCollide = false end
                    if head then head.CanCollide = false end
                    if torso then torso.CanCollide = false end
                    if lowerTorso then lowerTorso.CanCollide = false end
                end
            end)
        end
    else
        if noclipConnection then
            noclipConnection:Disconnect()
            noclipConnection = nil
        end
    end
end

local currentTween = nil

local function setAutoFarm(state)
    Settings.AutoFarm = state
    toggleNoclip(state)
    local char = LocalPlayer.Character
    local hum = char and char:FindFirstChildWhichIsA("Humanoid")
    if hum then
        hum.PlatformStand = state
        hum:SetStateEnabled(Enum.HumanoidStateType.Jumping, not state)
        hum:SetStateEnabled(Enum.HumanoidStateType.Freefall, not state)
        if not state then
            hum:ChangeState(Enum.HumanoidStateType.GettingUp)
        end
    end
    if not state and currentTween then
        currentTween:Cancel()
        currentTween = nil
    end
end

local function getCoinContainer()
    local cc = Workspace:FindFirstChild("CoinContainer", true)
    if cc and #cc:GetChildren() > 0 then
        return cc
    end
    for _, obj in ipairs(Workspace:GetChildren()) do
        local c = obj:FindFirstChild("CoinContainer")
        if c and #c:GetChildren() > 0 then
            return c
        end
    end
    return nil
end

local function getGunDrop()
    return Workspace:FindFirstChild("GunDrop", true)
end

-- Координаты лобби
local function getLobbyCFrame()
    local lobby = Workspace:FindFirstChild("Lobby") or Workspace:FindFirstChild("LobbyModel")
    if lobby then
        local spawns = lobby:FindFirstChild("Spawns") or lobby:FindFirstChild("SpawnLocations")
        if spawns then
            local sp = spawns:FindFirstChildWhichIsA("BasePart", true)
            if sp then return sp.CFrame end
        end
        local part = lobby:FindFirstChildWhichIsA("BasePart", true)
        if part then return part.CFrame end
    end
    return CFrame.new(-108, 140, -11)
end

local function isInLobby(root)
    if not root then return false end
    local lobbyCF = getLobbyCFrame()
    local dist = (root.Position - lobbyCF.Position).Magnitude
    return dist < 60
end

-- Определение ролей
local cachedRoles = { murderer = nil, sheriff = nil, myRole = "Innocent" }
local lastRolesCheck = 0

local function getRoles()
    local now = tick()
    if (now - lastRolesCheck) < 0.1 then
        return cachedRoles
    end
    lastRolesCheck = now

    local roles = { murderer = nil, sheriff = nil, myRole = "Innocent" }

    local function checkPlayerTool(player)
        local hasKnife, hasGun = false, false
        local function scanContainer(container)
            if not container then return end
            for _, item in ipairs(container:GetChildren()) do
                if item:IsA("Tool") then
                    local n = item.Name:lower()
                    if n:find("gun") or n:find("revolver") or n:find("pistol") or n:find("luger") or n:find("blaster") or n:find("laser") then
                        hasGun = true
                    elseif n:find("knife") or n:find("blade") or n:find("dagger") or n:find("sword") or n:find("axe") or n:find("scythe") or n:find("cutter") or n:find("cleaver") then
                        hasKnife = true
                    elseif not (n:find("radio") or n:find("boombox") or n:find("toy") or n:find("emote") or n:find("candy") or n:find("potion") or n:find("pizza") or n:find("drink")) then
                        if item:FindFirstChild("GunServer") or item:FindFirstChild("GunLocal") or item:FindFirstChild("Shoot") then
                            hasGun = true
                        else
                            hasKnife = true
                        end
                    end
                end
            end
        end

        scanContainer(player.Character)
        scanContainer(player:FindFirstChild("Backpack"))

        return hasKnife, hasGun
    end

    local myKnife, myGun = checkPlayerTool(LocalPlayer)
    if myKnife then
        roles.myRole = "Murderer"
    elseif myGun then
        roles.myRole = "Sheriff"
    end

    for _, player in ipairs(Players:GetPlayers()) do
        if player ~= LocalPlayer and player.Character then
            local k, g = checkPlayerTool(player)
            if k then
                roles.murderer = player
            elseif g then
                roles.sheriff = player
            end
        end
    end

    cachedRoles = roles
    return roles
end

-- Авто-открытие магазина
task.spawn(function()
    task.wait(3)
    pcall(function()
        local playerGui = LocalPlayer:FindFirstChild("PlayerGui")
        if not playerGui then return end
        local mainGui = playerGui:FindFirstChild("MainGUI")
        if not mainGui then return end

        local lobby = mainGui:FindFirstChild("Lobby")
        local dock = lobby and lobby:FindFirstChild("Dock")
        local shopBtn = dock and dock:FindFirstChild("Shop")
        if shopBtn and shopBtn:IsA("GuiButton") then
            if getconnections then
                for _, c in ipairs(getconnections(shopBtn.MouseButton1Click)) do c:Fire() end
                for _, c in ipairs(getconnections(shopBtn.Activated)) do c:Fire() end
            end
        end
    end)
end)

-- ==================== ЗАЩИЩЕННЫЙ ПАРСЕР СУМКИ, МОНЕТ И УРОВНЯ ====================
local function getPlayerCoins()
    local coins = sessionCoinsFarmed
    pcall(function()
        local playerGui = LocalPlayer:FindFirstChild("PlayerGui")
        if playerGui then
            local mainGui = playerGui:FindFirstChild("MainGUI")
            if mainGui then
                for _, obj in ipairs(mainGui:GetDescendants()) do
                    if obj:IsA("TextLabel") and obj.Visible and obj.Text ~= "" then
                        local p = obj.Parent
                        local pName = p and p.Name:lower() or ""
                        local oName = obj.Name:lower()
                        if oName:find("coin") or oName:find("currency") or pName:find("coin") or pName:find("currency") or pName:find("gold") then
                            local numStr = obj.Text:gsub("%D", "")
                            local n = tonumber(numStr)
                            if n and n >= 0 and n < 100000000 then
                                coins = math.max(coins, n)
                            end
                        end
                    end
                end
            end
        end
        local leaderstats = LocalPlayer:FindFirstChild("leaderstats")
        if leaderstats then
            local c = leaderstats:FindFirstChild("Coins") or leaderstats:FindFirstChild("Coin") or leaderstats:FindFirstChild("Gold")
            if c and tonumber(c.Value) then
                coins = math.max(coins, tonumber(c.Value))
            end
        end
    end)
    return coins
end

local function getCoinBagCount()
    -- 1. Если раунд не идет (в лобби нет монет) — сумка ВСЕГДА 0!
    local container = getCoinContainer()
    if not container or #container:GetChildren() == 0 then
        return 0
    end

    local count = 0

    pcall(function()
        local playerGui = LocalPlayer:FindFirstChild("PlayerGui")
        if not playerGui then return end
        local mainGui = playerGui:FindFirstChild("MainGUI")
        if not mainGui then return end

        local gameGui = mainGui:FindFirstChild("Game")
        local coinBag = gameGui and (gameGui:FindFirstChild("CoinBag") or gameGui:FindFirstChild("Bag"))

        -- 2. Читаем строго из контейнера Game.CoinBag
        if coinBag then
            for _, lbl in ipairs(coinBag:GetDescendants()) do
                if lbl:IsA("TextLabel") and lbl.Visible and lbl.TextTransparency < 0.5 and lbl.Text ~= "" then
                    local t = lbl.Text:lower()
                    if t:find("full") then
                        count = Settings.MaxBagCapacity
                        return
                    end
                    local n = tonumber(lbl.Text:match("(%d+)"))
                    if n and n <= Settings.MaxBagCapacity then
                        count = math.max(count, n)
                    end
                end
            end
        end

        -- 3. Резервный скан в игре С ИСКЛЮЧЕНИЕМ списка игроков (Leaderboard)
        if count == 0 and gameGui then
            local camera = Workspace.CurrentCamera
            local viewportSize = camera and camera.ViewportSize or Vector2.new(1920, 1080)

            for _, lbl in ipairs(gameGui:GetDescendants()) do
                local inLeaderboard = lbl:FindFirstAncestor("Leaderboard") or lbl:FindFirstAncestor("PlayerList") or
                    lbl:FindFirstAncestor("Dock") or lbl:FindFirstAncestor("Shop")
                if not inLeaderboard and lbl:IsA("TextLabel") and lbl.Visible and lbl.TextTransparency < 0.5 and lbl.Text ~= "" then
                    local pos = lbl.AbsolutePosition
                    if pos.X > (viewportSize.X * 0.65) and pos.Y > (viewportSize.Y * 0.65) then
                        local t = lbl.Text:lower():gsub("%s+", "")
                        if t:find("full") then
                            count = Settings.MaxBagCapacity
                            return
                        end
                        local n = tonumber(lbl.Text:match("(%d+)"))
                        if n and n <= Settings.MaxBagCapacity then
                            count = math.max(count, n)
                        end
                    end
                end
            end
        end
    end)

    return count
end

local function getAccountStats()
    local currentBag = getCoinBagCount()
    lastKnownCoins = math.max(lastKnownCoins, getPlayerCoins())

    local stats = {
        username = LocalPlayer.Name,
        userId = LocalPlayer.UserId,
        status = "FARMING",
        level = lastKnownLevel,
        bag = currentBag,
        maxBag = Settings.MaxBagCapacity,
        coins = lastKnownCoins,
        jobId = game.JobId,
        updatedAt = os.time(),
        timestamp = os.date("%Y-%m-%d %H:%M:%S")
    }

    local playerGui = LocalPlayer:FindFirstChild("PlayerGui")
    if not playerGui then return stats end

    -- Уровень из TAB
    pcall(function()
        for _, desc in ipairs(playerGui:GetDescendants()) do
            if desc:IsA("TextLabel") and (desc.Text == LocalPlayer.Name or desc.Text == LocalPlayer.DisplayName) then
                local row = desc.Parent
                if row then
                    for _, sibling in ipairs(row:GetDescendants()) do
                        if sibling:IsA("TextLabel") and sibling ~= desc and sibling.Text and sibling.Text ~= "" then
                            local clean = sibling.Text:gsub("%D", "")
                            local n = tonumber(clean)
                            if n and n > 0 and n < 1000 and not sibling.Text:find("/") and not sibling.Text:find("%+") and not sibling.Text:find(":") then
                                lastKnownLevel = n
                            end
                        end
                    end
                end
            end
        end
    end)

    stats.level = lastKnownLevel
    stats.bag = currentBag
    stats.coins = lastKnownCoins

    return stats
end

local function exportStatsToFile()
    if not writefile or isGameExiting then return end
    local stats = getAccountStats()

    pcall(function()
        writefile("stats_" .. tostring(LocalPlayer.UserId) .. ".json", HttpService:JSONEncode(stats))
    end)

    local logName = Settings.CustomLogFileName
    if logName and logName ~= "" then
        pcall(function()
            local existing = ""
            if isfile and isfile(logName) then
                existing = readfile(logName) or ""
            end

            -- Если бот уже достиг 100 лвл, переносим/удаляем его из активного лога
            if stats.level >= 100 then
                local remaining = {}
                for line in string.gmatch(existing, "[^\r\n]+") do
                    if not line:find(stats.username, 1, true) then
                        table.insert(remaining, line)
                    end
                end
                writefile(logName, table.concat(remaining, "\n") .. (#remaining > 0 and "\n" or ""))
                return
            end

            -- Записываем строго 1 строку на 1 акк: ник, лвл и объективный трекинг мешка
            local updated = false
            local newLines = {}
            local bagCount = stats.bag or 0
            local maxBag = stats.maxBag or Settings.MaxBagCapacity or 40
            local statLine = string.format("User: %s | Level: %d | Bag: %d/%d", stats.username, stats.level, bagCount, maxBag)

            for line in string.gmatch(existing, "[^\r\n]+") do
                if line:find(stats.username, 1, true) then
                    if not updated then
                        table.insert(newLines, statLine)
                        updated = true
                    end
                else
                    if line:match("%S") then
                        table.insert(newLines, line)
                    end
                end
            end

            if not updated then
                table.insert(newLines, statLine)
            end

            table.sort(newLines)
            writefile(logName, table.concat(newLines, "\n") .. "\n")
        end)
    end
end

task.spawn(function()
    while true do
        task.wait(Settings.ExportInterval or 5)
        if Settings.AutoExportStats then
            pcall(exportStatsToFile)
        end
    end
end)

-- ==================== ЗАЩИЩЕННЫЙ СЕРВЕРХОП И АНТИ-СТОЛКНОВЕНИЕ ====================
local skippedServers = {}

local lastLocalHopTime = 0

local function canTeleport()
    -- 1. Локальный кулдаун окна: не чаще раза в 120 секунд (защита от частых рестартов и банов)
    if (tick() - lastLocalHopTime) < 120 then
        return false
    end
    -- 2. Защита от хопа в первые 90 секунд после входа в игру (дай серверу загрузиться)
    if (tick() - scriptLoadTime) < 90 then
        return false
    end
    -- 3. Межпроцессный лок: минимум 15 секунд разницы между хопами разных ботов
    local lockFile = "teleport_lock.json"
    if isfile and isfile(lockFile) then
        local ok, data = pcall(function() return HttpService:JSONDecode(readfile(lockFile)) end)
        if ok and type(data) == "table" and data.timestamp then
            if (tick() - data.timestamp) < 15 then
                return false
            end
        end
    end
    return true
end

local function setTeleportLock()
    if writefile then
        pcall(function()
            writefile("teleport_lock.json", HttpService:JSONEncode({ timestamp = tick() }))
        end)
    end
end

local function registerMyServer()
    if not writefile then return end
    pcall(function()
        local data = {}
        if isfile and isfile("bot_servers.json") then
            local ok, parsed = pcall(function() return HttpService:JSONDecode(readfile("bot_servers.json")) end)
            if ok and type(parsed) == "table" then data = parsed end
        end
        local now = tick()
        for sid, info in pairs(data) do
            if type(info) ~= "table" or not info.time or (now - info.time > 180) then
                data[sid] = nil
            end
        end
        data[game.JobId] = {
            userId = LocalPlayer.UserId,
            name = LocalPlayer.Name,
            time = now
        }
        writefile("bot_servers.json", HttpService:JSONEncode(data))
    end)
end

local function unregisterMyServer()
    if not writefile then return end
    pcall(function()
        if isfile and isfile("bot_servers.json") then
            local ok, data = pcall(function() return HttpService:JSONDecode(readfile("bot_servers.json")) end)
            if ok and type(data) == "table" and data[game.JobId] then
                data[game.JobId] = nil
                writefile("bot_servers.json", HttpService:JSONEncode(data))
            end
        end
    end)
end

local function hopToPopulatedServer(force)
    -- Жесткий лимит: даже при force запрещено хопать чаще чем раз в 60с (спасает от Arkose/Passport)
    if (tick() - lastLocalHopTime) < 60 then
        return
    end
    if not force and not canTeleport() then
        return
    end
    lastLocalHopTime = tick()
    setTeleportLock()

    notifyUser("Server Hunter", "Ищем свободный сервер...", 3)
    unregisterMyServer()

    local targetServerId = nil

    pcall(function()
        local botServers = {}
        if isfile and isfile("bot_servers.json") then
            pcall(function()
                local bdata = HttpService:JSONDecode(readfile("bot_servers.json"))
                if type(bdata) == "table" then
                    for sid, info in pairs(bdata) do
                        if type(info) == "table" and info.time and (tick() - info.time < 180) then
                            botServers[sid] = true
                        end
                    end
                end
            end)
        end

        local urls = {
            "https://games.roblox.com/v1/games/" .. game.PlaceId .. "/servers/Public?sortOrder=Desc&limit=100",
            "https://games.roblox.com/v1/games/" .. game.PlaceId .. "/servers/Public?sortOrder=Asc&limit=100"
        }

        for _, url in ipairs(urls) do
            local ok, raw = pcall(function() return game:HttpGet(url) end)
            if ok and raw then
                local sdata = HttpService:JSONDecode(raw)
                if sdata and sdata.data and #sdata.data > 0 then
                    local validServers = {}
                    for _, s in ipairs(sdata.data) do
                        local plrs = s.playing or 0
                        local maxP = s.maxPlayers or 12
                        if s.id ~= game.JobId and not skippedServers[s.id] and not botServers[s.id] then
                            if plrs >= 4 and plrs < maxP then
                                table.insert(validServers, s.id)
                            end
                        end
                    end

                    if #validServers == 0 then
                        for _, s in ipairs(sdata.data) do
                            local plrs = s.playing or 0
                            local maxP = s.maxPlayers or 12
                            if s.id ~= game.JobId and not skippedServers[s.id] and not botServers[s.id] and plrs < maxP then
                                table.insert(validServers, s.id)
                            end
                        end
                    end

                    if #validServers > 0 then
                        targetServerId = validServers[math.random(1, #validServers)]
                        break
                    end
                end
            end
        end
    end)

    if targetServerId then
        skippedServers[targetServerId] = true
        notifyUser("Server Hunter", "Телепортация на сервер...", 3)
        local ok = pcall(function()
            TeleportService:TeleportToPlaceInstance(game.PlaceId, targetServerId, LocalPlayer)
        end)
        if not ok then
            TeleportService:Teleport(game.PlaceId, LocalPlayer)
        end
    else
        notifyUser("Server Hunter", "Переход на случайный публичный сервер...", 3)
        pcall(function()
            TeleportService:Teleport(game.PlaceId, LocalPlayer)
        end)
    end
end

TeleportService.TeleportInitFailed:Connect(function(player, result, errorMessage)
    if player == LocalPlayer then
        warn("[Teleport Failed]: ", errorMessage)
        task.wait(math.random(2, 4))
        hopToPopulatedServer(true)
    end
end)

local function isOtherBot(p)
    if not p or p == LocalPlayer then return false end
    local prefix = Settings.BotUsernamePrefix or "Fmr_"
    if p.Name:sub(1, #prefix) == prefix or p.Name:match("^ym1co_") then
        return true
    end
    if isfile and isfile("bot_ids.json") then
        local ok, list = pcall(function() return HttpService:JSONDecode(readfile("bot_ids.json")) end)
        if ok and type(list) == "table" and table.find(list, p.UserId) then
            return true
        end
    end
    return false
end

local handledCollisionBots = {}

local function triggerGuiClick(elem)
    if not elem then return end

    pcall(function()
        if firesignal then
            if elem:IsA("GuiButton") or elem:IsA("TextButton") or elem:IsA("ImageButton") then
                pcall(function() firesignal(elem.Activated) end)
                pcall(function() firesignal(elem.MouseButton1Click) end)
                pcall(function() firesignal(elem.MouseButton1Down) end)
                pcall(function() firesignal(elem.MouseButton1Up) end)
            end
        end
    end)

    pcall(function()
        if getconnections then
            for _, sigName in ipairs({"Activated", "MouseButton1Click", "MouseButton1Down", "MouseButton1Up"}) do
                if elem[sigName] then
                    for _, conn in ipairs(getconnections(elem[sigName])) do
                        pcall(function() conn:Fire() end)
                    end
                end
            end
        end
    end)

    pcall(function()
        local vim = game:GetService("VirtualInputManager")
        if vim and elem.AbsolutePosition and elem.AbsoluteSize then
            local sz = elem.AbsoluteSize
            if sz.X > 5 and sz.Y > 5 then
                local cx = math.floor(elem.AbsolutePosition.X + sz.X / 2)
                local cy = math.floor(elem.AbsolutePosition.Y + sz.Y / 2)
                if cx > 0 and cy > 0 then
                    vim:SendMouseButtonEvent(cx, cy, 0, true, game, 0)
                    task.wait(0.03)
                    vim:SendMouseButtonEvent(cx, cy, 0, false, game, 0)
                end
            end
        end
    end)
end

local function confirmBlockPrompt()
    local coreGui = game:GetService("CoreGui")
    if not coreGui then return false end

    local guis = {coreGui}
    pcall(function()
        if LocalPlayer and LocalPlayer:FindFirstChild("PlayerGui") then
            table.insert(guis, LocalPlayer.PlayerGui)
        end
    end)

    local clicked = false

    for _, container in ipairs(guis) do
        pcall(function()
            for _, desc in ipairs(container:GetDescendants()) do
                local text = ""
                if desc:IsA("TextLabel") or desc:IsA("TextButton") then
                    text = (desc.Text or ""):gsub("^%s*(.-)%s*$", "%1"):lower()
                end

                -- 1. Подтверждение блокировки: точное совпадение "block" / "заблокировать"
                if text == "block" or text == "заблокировать" then
                    triggerGuiClick(desc)
                    if desc.Parent then
                        triggerGuiClick(desc.Parent)
                        if desc.Parent.Parent then
                            triggerGuiClick(desc.Parent.Parent)
                        end
                    end
                    clicked = true
                -- 2. Закрытие модалки ошибки ("Error Blocking Player" -> "Okay")
                elseif text == "okay" or text == "ok" or text == "хорошо" or text == "понятно" then
                    local anc = desc.Parent
                    local isBlockRelated = false
                    for _ = 1, 4 do
                        if anc then
                            for _, child in ipairs(anc:GetChildren()) do
                                local ct = (child:IsA("TextLabel") or child:IsA("TextButton")) and (child.Text or ""):lower() or ""
                                if ct:find("block") or ct:find("заблокировать") then
                                    isBlockRelated = true
                                    break
                                end
                            end
                            if isBlockRelated then break end
                            anc = anc.Parent
                        end
                    end
                    if isBlockRelated then
                        triggerGuiClick(desc)
                        if desc.Parent then triggerGuiClick(desc.Parent) end
                        clicked = true
                    end
                -- 3. Проверка по системным именам кнопок Roblox CoreGui
                elseif (desc.Name == "ConfirmButton" or desc.Name == "ButtonPrimary" or desc.Name == "PrimaryButton") and (desc:IsA("GuiButton") or desc:IsA("Frame")) then
                    local isBlockModal = false
                    local anc = desc.Parent
                    for _ = 1, 4 do
                        if anc then
                            for _, child in ipairs(anc:GetChildren()) do
                                local cText = (child:IsA("TextLabel") or child:IsA("TextButton")) and (child.Text or ""):lower() or ""
                                if cText:find("block") or cText:find("заблокировать") then
                                    isBlockModal = true
                                    break
                                end
                            end
                            if isBlockModal then break end
                            anc = anc.Parent
                        end
                    end
                    if isBlockModal then
                        triggerGuiClick(desc)
                        clicked = true
                    end
                end
            end
        end)
    end

    return clicked
end

local function dismissBlockPromptIfStuck()
    local coreGui = game:GetService("CoreGui")
    if not coreGui then return end
    pcall(function()
        for _, desc in ipairs(coreGui:GetDescendants()) do
            if desc:IsA("TextLabel") or desc:IsA("TextButton") then
                local t = (desc.Text or ""):gsub("^%s*(.-)%s*$", "%1"):lower()
                if t == "cancel" or t == "отмена" then
                    local anc = desc.Parent
                    local isBlockModal = false
                    for _ = 1, 4 do
                        if anc then
                            for _, ch in ipairs(anc:GetChildren()) do
                                local chText = (ch:IsA("TextLabel") or ch:IsA("TextButton")) and (ch.Text or ""):lower() or ""
                                if chText:find("block") or chText:find("заблокировать") then
                                    isBlockModal = true
                                    break
                                end
                            end
                            if isBlockModal then break end
                            anc = anc.Parent
                        end
                    end
                    if isBlockModal then
                        triggerGuiClick(desc)
                        if desc.Parent then triggerGuiClick(desc.Parent) end
                    end
                end
            end
        end
    end)
end

-- Мгновенная реакция при появлении окна блокировки
pcall(function()
    CoreGui.DescendantAdded:Connect(function(desc)
        pcall(function()
            if desc:IsA("TextLabel") or desc:IsA("TextButton") then
                local t = (desc.Text or ""):gsub("^%s*(.-)%s*$", "%1"):lower()
                if t == "block" or t == "заблокировать" then
                    task.spawn(function()
                        for _ = 1, 10 do
                            task.wait(0.05)
                            if confirmBlockPrompt() then break end
                        end
                    end)
                end
            end
        end)
    end)
end)

local lowPlayerCountSince = 0

local function checkBotCollision()
    if not Settings.AutoServerHopOnBotCollision then return end
    -- Не хопаем в первые 60 секунд после входа в игру
    if (tick() - scriptLoadTime) < 60 then return end

    for _, p in ipairs(Players:GetPlayers()) do
        if isOtherBot(p) then
            local lastHandled = handledCollisionBots[p.UserId] or 0
            if (tick() - lastHandled) < 60 then
                return
            end
            handledCollisionBots[p.UserId] = tick()

            pcall(function()
                if appendfile then
                    appendfile("block_queue.txt", HttpService:JSONEncode({
                        me = LocalPlayer.UserId,
                        target = p.UserId,
                        meName = LocalPlayer.Name,
                        targetName = p.Name
                    }) .. "\n")
                end
            end)

            pcall(function()
                StarterGui:SetCore("PromptBlockPlayer", p)
            end)

            -- Цикл авто-подтверждения кнопки "Block"
            task.spawn(function()
                local confirmed = false
                for _ = 1, 25 do
                    task.wait(0.1)
                    if confirmBlockPrompt() then
                        confirmed = true
                        task.wait(0.15)
                        confirmBlockPrompt()
                        break
                    end
                end
                if not confirmed then
                    dismissBlockPromptIfStuck()
                end
            end)

            -- Переход только если бот пробыл на сервере хотя бы 90с (защита от Passport/Arkose)
            if LocalPlayer.UserId > p.UserId then
                if (tick() - scriptLoadTime) >= 90 and (tick() - lastLocalHopTime) >= 90 then
                    notifyUser("Anti-Collision", "Обнаружен бот " .. p.Name .. "! Плавный уход через 10-15с...", 3)
                    task.wait(math.random(10, 15))
                    hopToPopulatedServer(false)
                    return
                else
                    notifyUser("Anti-Collision", "Бот " .. p.Name .. " рядом, но мы недавно зашли. Доигрываем раунд.", 3)
                end
            else
                notifyUser("Anti-Collision", "Бот " .. p.Name .. " обнаружен. Я остаюсь.", 3)
            end
        end
    end
end

Players.PlayerAdded:Connect(function(p)
    if isOtherBot(p) then
        task.wait(2)
        checkBotCollision()
    end
end)

local function checkServerPopulation()
    if not Settings.AutoHopLowPlayerCount then return end
    -- Не трогаем сервер первые 120 секунд после захода
    if (tick() - scriptLoadTime) < 120 then return end

    local count = #Players:GetPlayers()
    local minPlayers = Settings.MinPlayersInServer or 4
    if count < minPlayers then
        if lowPlayerCountSince == 0 then
            lowPlayerCountSince = tick()
        elseif (tick() - lowPlayerCountSince) >= 45 then
            -- Сервер реально пустой более 45 секунд подряд
            notifyUser("Server Monitor", "Низкий онлайн (" .. count .. " игр. >45с). Переход...", 3)
            lowPlayerCountSince = 0
            hopToPopulatedServer(false)
        end
    else
        lowPlayerCountSince = 0
    end
end

task.spawn(function()
    while true do
        task.wait(2.0)
        pcall(confirmBlockPrompt)
        task.wait(2.0)
        pcall(registerMyServer)
        pcall(checkBotCollision)
        pcall(checkServerPopulation)
    end
end)

local function touchCoin(coinPart, root)
    if not coinPart or not root then return end
    sessionCoinsFarmed = sessionCoinsFarmed + 1
    lastKnownCoins = math.max(lastKnownCoins, sessionCoinsFarmed)
    if firetouchinterest then
        pcall(function()
            firetouchinterest(root, coinPart, 0)
            task.wait(0.01)
            firetouchinterest(root, coinPart, 1)
        end)
    end
end

-- ==================== БЕЗОПАСНЫЕ ТОЧКИ ====================
local cachedUndergroundSpot = nil
local function getUndergroundCFrame(root)
    if cachedUndergroundSpot then return cachedUndergroundSpot end
    if root then
        cachedUndergroundSpot = CFrame.new(root.Position.X, root.Position.Y - 18, root.Position.Z)
        return cachedUndergroundSpot
    end
    return CFrame.new(0, -15, 0)
end

local function getKiteCFrame(root, murdererPos, desiredDist)
    local dir = (root.Position - murdererPos).Unit
    local targetPos = murdererPos + (dir * desiredDist)
    return CFrame.new(targetPos.X, root.Position.Y, targetPos.Z)
end

local ignoredCoins = {}

local function getNearestCoin(root)
    local container = getCoinContainer()
    if not container or not root then return nil end

    local myPos = root.Position
    local nearest = nil
    local minDist = math.huge

    local now = tick()
    for c, exp in pairs(ignoredCoins) do
        if now >= exp then ignoredCoins[c] = nil end
    end

    for _, coin in ipairs(container:GetChildren()) do
        if not ignoredCoins[coin] then
            local part = coin:IsA("BasePart") and coin or coin:FindFirstChildWhichIsA("BasePart", true)
            if part and not ignoredCoins[part] then
                local d = (part.Position - myPos).Magnitude
                if d < minDist then
                    minDist = d
                    nearest = part
                end
            end
        end
    end
    return nearest
end

-- Параллельный кайт от маньяка
task.spawn(function()
    while true do
        task.wait(0.2)
        pcall(function()
            if not Settings.AvoidMurderer or not Settings.AutoFarm then return end
            local char = LocalPlayer.Character
            local hum = char and char:FindFirstChildWhichIsA("Humanoid")
            local root = char and char:FindFirstChild("HumanoidRootPart")
            if not (char and hum and root and hum.Health > 0) then return end

            local container = getCoinContainer()
            if container and #container:GetChildren() > 0 and isInLobby(root) then return end

            local roles = getRoles()
            if roles.myRole == "Murderer" then return end

            if roles.murderer and roles.murderer.Character and roles.murderer.Character:FindFirstChild("HumanoidRootPart") then
                local mPos = roles.murderer.Character.HumanoidRootPart.Position
                local myDist = (mPos - root.Position).Magnitude

                if myDist < Settings.AvoidDistance then
                    if currentTween then
                        currentTween:Cancel()
                        currentTween = nil
                    end
                    root.AssemblyLinearVelocity = Vector3.zero

                    local safeSpot
                    if Settings.AvoidAction == "Kite" then
                        safeSpot = getKiteCFrame(root, mPos, 48)
                    else
                        safeSpot = getUndergroundCFrame(root)
                    end

                    local tw = TweenService:Create(root, TweenInfo.new(0.3, Enum.EasingStyle.Linear),
                        { CFrame = safeSpot })
                    tw:Play()
                    tw.Completed:Wait()
                end
            end
        end)
    end
end)

-- ==================== СТРЕЛЬБА И АТАКА МАНЬЯКА (ШЕРИФ ПОСЛЕДНИМ) ====================
local function executeCombatWin(root, char, roles)
    local hum = char:FindFirstChildWhichIsA("Humanoid")
    if not hum or hum.Health <= 0 then return end

    -- 1. ЕСЛИ У НАС ЕСТЬ ПИСТОЛЕТ (ШЕРИФ / ПОДОБРАННЫЙ ПИСТОЛЕТ)
    local function isGunItem(item)
        if not (item and item:IsA("Tool")) then return false end
        local n = item.Name:lower()
        if n:find("gun") or n:find("revolver") or n:find("pistol") or n:find("luger") or n:find("blaster") or n:find("laser") then
            return true
        end
        if item:FindFirstChild("GunServer") or item:FindFirstChild("GunLocal") or item:FindFirstChild("Shoot") or item:FindFirstChild("GunDrop") then
            return true
        end
        return false
    end

    local gun = nil
    for _, item in ipairs(char:GetChildren()) do
        if isGunItem(item) then
            gun = item
            break
        end
    end
    if not gun then
        local bp = LocalPlayer:FindFirstChild("Backpack")
        if bp then
            for _, item in ipairs(bp:GetChildren()) do
                if isGunItem(item) then
                    gun = item
                    hum:EquipTool(gun)
                    break
                end
            end
        end
    end

    if gun then
        -- Ждем полной физической экипировки оружия в руку
        if gun.Parent ~= char then
            hum:EquipTool(gun)
            local t0 = tick()
            while gun.Parent ~= char and (tick() - t0) < 0.5 do
                task.wait(0.03)
            end
        end
        task.wait(0.1)

        local targetMurderer = roles.murderer
        if not targetMurderer or not targetMurderer.Character then
            for _, p in ipairs(Players:GetPlayers()) do
                if p ~= LocalPlayer and p.Character then
                    for _, item in ipairs(p.Character:GetChildren()) do
                        if item:IsA("Tool") and (item.Name:lower():find("knife") or item.Name:lower():find("blade") or item.Name:lower():find("dagger") or item.Name:lower():find("sword")) then
                            targetMurderer = p
                            break
                        end
                    end
                    if not targetMurderer and p:FindFirstChild("Backpack") then
                        for _, item in ipairs(p.Backpack:GetChildren()) do
                            if item:IsA("Tool") and (item.Name:lower():find("knife") or item.Name:lower():find("blade") or item.Name:lower():find("dagger") or item.Name:lower():find("sword")) then
                                targetMurderer = p
                                break
                            end
                        end
                    end
                end
                if targetMurderer then break end
            end
        end

        if targetMurderer and targetMurderer.Character then
            local mChar = targetMurderer.Character
            local mRoot = mChar:FindFirstChild("HumanoidRootPart")
            local mHum = mChar:FindFirstChildWhichIsA("Humanoid")
            local mHead = mChar:FindFirstChild("Head") or mRoot

            if mRoot and mHum and mHum.Health > 0 and mHead and mRoot.Position.Y > -50 then
                toggleNoclip(true)
                if currentTween then
                    currentTween:Cancel()
                    currentTween = nil
                end

                -- Временно включаем 3D-рендеринг для 100% точности лучей и Mouse.Hit
                pcall(function() RunService:Set3dRenderingEnabled(true) end)

                -- Функция выстрела ван-тапом: одновременный прострел через все сетевые и локальные каналы
                local function firePointBlank(targetHeadPos)
                    -- 1. Удаленные события стрельбы MM2
                    pcall(function()
                        local shootRemote = ReplicatedStorage:FindFirstChild("ShootGun", true)
                        if shootRemote and shootRemote:IsA("RemoteEvent") then
                            shootRemote:FireServer(1, targetHeadPos, "AH")
                            shootRemote:FireServer(targetHeadPos)
                            shootRemote:FireServer(1, targetHeadPos)
                            shootRemote:FireServer(targetHeadPos, root.Position)
                        end
                        local mainEvent = ReplicatedStorage:FindFirstChild("MainEvent", true)
                        if mainEvent and mainEvent:IsA("RemoteEvent") then
                            mainEvent:FireServer("ShootGun", targetHeadPos)
                            mainEvent:FireServer("ShootGun", 1, targetHeadPos, "AH")
                            mainEvent:FireServer("Shoot", targetHeadPos)
                            mainEvent:FireServer("ShootGun", targetHeadPos, root.Position)
                        end
                    end)

                    -- 2. Внутренние ремоуты оружия
                    pcall(function()
                        for _, desc in ipairs(gun:GetDescendants()) do
                            if desc:IsA("RemoteEvent") then
                                desc:FireServer(1, targetHeadPos, "AH")
                                desc:FireServer(targetHeadPos)
                                desc:FireServer(1, targetHeadPos)
                                desc:FireServer(mChar)
                                desc:FireServer(targetHeadPos, root.Position)
                            elseif desc:IsA("RemoteFunction") then
                                pcall(function() desc:InvokeServer(1, targetHeadPos, "AH") end)
                                pcall(function() desc:InvokeServer(targetHeadPos) end)
                            end
                        end
                    end)

                    -- 3. Активация инструмента и коннектов
                    pcall(function()
                        gun:Activate()
                        if getconnections then
                            for _, c in ipairs(getconnections(gun.Activated)) do
                                pcall(function() c:Fire() end)
                            end
                        end
                    end)

                    -- 4. Аимлок камеры и курсора мыши прямо в голову маньяка
                    pcall(function()
                        local cam = Workspace.CurrentCamera
                        local vp = cam.ViewportSize
                        local centerVec = Vector2.new(vp.X / 2, vp.Y / 2)
                        local sPoint, onScreen = cam:WorldToViewportPoint(targetHeadPos)
                        local targetVec = (onScreen and Vector2.new(sPoint.X, sPoint.Y)) or centerVec

                        local vim = game:GetService("VirtualInputManager")
                        if vim then
                            vim:SendMouseMoveEvent(targetVec.X, targetVec.Y, game)
                            vim:SendMouseButtonEvent(targetVec.X, targetVec.Y, 0, true, game, 0)
                            vim:SendMouseButtonEvent(targetVec.X, targetVec.Y, 0, false, game, 0)
                            vim:SendMouseButtonEvent(centerVec.X, centerVec.Y, 0, true, game, 0)
                            vim:SendMouseButtonEvent(centerVec.X, centerVec.Y, 0, false, game, 0)
                        end

                        VirtualUser:Button1Down(targetVec, cam.CFrame)
                        VirtualUser:Button1Up(targetVec, cam.CFrame)
                        VirtualUser:Button1Down(centerVec, cam.CFrame)
                        VirtualUser:Button1Up(centerVec, cam.CFrame)
                    end)

                    -- 5. Запасной клик
                    pcall(function()
                        if mouse1click then
                            mouse1click()
                        end
                    end)
                end

                -- ТЕЛЕПОРТАЦИЯ: СТРОГО СО СПИНЫ МАНЬЯКА (2.8 студа сзади, 1.4 студа выше головы)
                -- Маньяк бьет ножом ТОЛЬКО вперед! Находясь сзади, бот защищен от ножа на 100%!
                local tStart = tick()
                while (tick() - tStart) < 1.2 and hum.Health > 0 and mHum and mHum.Health > 0 and targetMurderer.Parent do
                    local headPart = mChar:FindFirstChild("Head") or mRoot
                    local targetHeadPos = headPart.Position
                    local lookDir = mRoot.CFrame.LookVector

                    -- Позиция вплотную за спиной маньяка (минус lookDir), глядя сверху вниз прямо в голову
                    local pointBlankBehindPos = targetHeadPos - (lookDir * 2.8) + Vector3.new(0, 1.4, 0)

                    root.AssemblyLinearVelocity = Vector3.zero
                    root.AssemblyAngularVelocity = Vector3.zero
                    root.CFrame = CFrame.lookAt(pointBlankBehindPos, targetHeadPos)
                    Workspace.CurrentCamera.CFrame = CFrame.lookAt(pointBlankBehindPos + Vector3.new(0, 0.4, 0), targetHeadPos)

                    firePointBlank(targetHeadPos)
                    task.wait(0.05)
                end

                pcall(function() RunService:Set3dRenderingEnabled(false) end)
                root.AssemblyLinearVelocity = Vector3.zero
                task.wait(0.1)
                return
            end
        end
    end

    -- 2. ЕСЛИ МЫ МАНЬЯК С НОЖОМ
    local knife = nil
    for _, item in ipairs(char:GetChildren()) do
        if item:IsA("Tool") and not (item.Name:lower():find("gun") or item.Name:lower():find("revolver") or item.Name:lower():find("pistol") or item.Name:lower():find("luger") or item.Name:lower():find("blaster") or item.Name:lower():find("laser")) then
            knife = item
            break
        end
    end
    if not knife then
        local bp = LocalPlayer:FindFirstChild("Backpack")
        if bp then
            for _, item in ipairs(bp:GetChildren()) do
                if item:IsA("Tool") and not (item.Name:lower():find("gun") or item.Name:lower():find("revolver") or item.Name:lower():find("pistol") or item.Name:lower():find("luger") or item.Name:lower():find("blaster") or item.Name:lower():find("laser")) then
                    knife = item
                    hum:EquipTool(knife)
                    task.wait(0.1)
                    break
                end
            end
        end
    end

    if knife then
        local victims = {}
        local sheriffPlayer = roles.sheriff

        -- ВАЖНО: Шерифа убиваем ПЕРВЫМ, чтобы он не успел достать пистолет!
        if sheriffPlayer and sheriffPlayer.Character then
            local sHum = sheriffPlayer.Character:FindFirstChildWhichIsA("Humanoid")
            local sRoot = sheriffPlayer.Character:FindFirstChild("HumanoidRootPart")
            if sHum and sRoot and sHum.Health > 0 and sRoot.Position.Y > -10 then
                table.insert(victims, sheriffPlayer)
            end
        end

        for _, victim in ipairs(Players:GetPlayers()) do
            if victim ~= LocalPlayer and victim ~= sheriffPlayer and victim.Character then
                local vHum = victim.Character:FindFirstChildWhichIsA("Humanoid")
                local vRoot = victim.Character:FindFirstChild("HumanoidRootPart")
                if vHum and vRoot and vHum.Health > 0 and vRoot.Position.Y > -10 then
                    table.insert(victims, victim)
                end
            end
        end

        for _, victim in ipairs(victims) do
            if victim.Character then
                local vHum = victim.Character:FindFirstChildWhichIsA("Humanoid")
                local vRoot = victim.Character:FindFirstChild("HumanoidRootPart")

                if vHum and vRoot and vHum.Health > 0 then
                    local attackPos = CFrame.new(vRoot.Position.X, math.max(vRoot.Position.Y + 1.5, 2), vRoot.Position.Z)
                    root.AssemblyLinearVelocity = Vector3.zero
                    root.CFrame = attackPos

                    knife:Activate()
                    touchCoin(vRoot, knife:FindFirstChild("Handle") or root)
                    task.wait(0.08)
                end
            end
        end

        root.AssemblyLinearVelocity = Vector3.zero
        local safeHover = CFrame.new(root.Position.X, math.max(root.Position.Y, 5), root.Position.Z)
        root.CFrame = safeHover
    end
end

-- ==================== ОСНОВНОЙ ЦИКЛ ФАРМА ====================
local emptyCoinsSince = nil

local function farmStep()
    local char = LocalPlayer.Character
    if not char then return end
    local hum = char:FindFirstChildWhichIsA("Humanoid")
    local root = char:FindFirstChild("HumanoidRootPart")

    if not (Settings.AutoFarm and hum and root and hum.Health > 0) then
        return
    end

    if isInLobby(root) then
        cachedUndergroundSpot = nil
        emptyCoinsSince = nil
        if hum.PlatformStand then
            hum.PlatformStand = false
            hum:ChangeState(Enum.HumanoidStateType.GettingUp)
        end
        if currentTween then
            currentTween:Cancel()
            currentTween = nil
        end
        return
    end

    local roles = getRoles()
    local currentCoins = getCoinBagCount()

    -- 1. СТРОГИЙ ПРИОРИТЕТ: ЕСЛИ МЕШОК ПОЛОН (>= MaxBagCapacity, 40 МОНЕТ) -> ВЫИГРЫВАЕМ РАУНД!
    if currentCoins >= Settings.MaxBagCapacity then
        emptyCoinsSince = nil
        root.AssemblyLinearVelocity = Vector3.zero
        if currentTween then
            currentTween:Cancel(); currentTween = nil
        end

        local bp = LocalPlayer:FindFirstChild("Backpack")
        local hasGunOrKnife = false
        for _, item in ipairs(char:GetChildren()) do
            if item:IsA("Tool") then
                hasGunOrKnife = true
                break
            end
        end
        if not hasGunOrKnife and bp then
            for _, item in ipairs(bp:GetChildren()) do
                if item:IsA("Tool") then
                    hasGunOrKnife = true
                    break
                end
            end
        end

        if hasGunOrKnife or roles.myRole == "Sheriff" or roles.myRole == "Murderer" then
            executeCombatWin(root, char, roles)
            task.wait(1.5)
            return
        end

        if Settings.ActionOnFull == "Lobby" or Settings.ActionOnFull == "CombatWin" then
            local lobbySpot = getLobbyCFrame()
            local tw = TweenService:Create(root, TweenInfo.new(0.5, Enum.EasingStyle.Linear), { CFrame = lobbySpot })
            tw:Play()
            tw.Completed:Wait()
            task.wait(1.5)
        elseif Settings.ActionOnFull == "Underground" then
            toggleNoclip(true)
            local safeSpot = getUndergroundCFrame(root)
            local tw = TweenService:Create(root, TweenInfo.new(0.35, Enum.EasingStyle.Linear), { CFrame = safeSpot })
            tw:Play()
            tw.Completed:Wait()
            task.wait(1.5)
        elseif Settings.ActionOnFull == "Server Hop" then
            hopToPopulatedServer()
            task.wait(5)
        end
        return
    end

    -- 2. МЕШОК НЕ ПОЛОН: СТРОГО ФАРМИМ МОНЕТЫ И НЕ ЛЕЗЕМ К МАНЬЯКУ!
    local container = getCoinContainer()
    if not container or #container:GetChildren() == 0 then
        cachedUndergroundSpot = nil
        if hum.PlatformStand then
            hum.PlatformStand = false
            hum:ChangeState(Enum.HumanoidStateType.GettingUp)
        end
        if currentTween then
            currentTween:Cancel()
            currentTween = nil
        end

        -- Запасной случай: если монет нет на карте больше 8 секунд и у нас есть оружие
        if not emptyCoinsSince then
            emptyCoinsSince = tick()
        elseif (tick() - emptyCoinsSince) > 8.0 and currentCoins >= Settings.MaxBagCapacity then
            local bp = LocalPlayer:FindFirstChild("Backpack")
            local hasGunOrKnife = false
            for _, item in ipairs(char:GetChildren()) do
                if item:IsA("Tool") then hasGunOrKnife = true; break end
            end
            if not hasGunOrKnife and bp then
                for _, item in ipairs(bp:GetChildren()) do
                    if item:IsA("Tool") then hasGunOrKnife = true; break end
                end
            end
            if hasGunOrKnife or roles.myRole == "Sheriff" or roles.myRole == "Murderer" then
                executeCombatWin(root, char, roles)
                task.wait(1.5)
                return
            end
        end
        return
    end

    emptyCoinsSince = nil

    if not hum.PlatformStand then
        hum.PlatformStand = true
    end

    if Settings.AutoGrabGun then
        local gun = getGunDrop()
        if gun and gun:IsDescendantOf(Workspace) then
            local gp = gun:IsA("BasePart") and gun or gun:FindFirstChildWhichIsA("BasePart", true)
            if gp then
                local dist = (gp.Position - root.Position).Magnitude
                local tTime = math.clamp(dist / Settings.FarmSpeed, 0.05, 1.5)
                local tw = TweenService:Create(root, TweenInfo.new(tTime, Enum.EasingStyle.Linear),
                    { CFrame = gp.CFrame + Vector3.new(0, 1.5, 0) })
                tw:Play()
                tw.Completed:Wait()
                touchCoin(gp, root)
                task.wait(0.1)
                if Settings.GunPriority then return end
            end
        end
    end

    local targetPart = getNearestCoin(root)
    if targetPart and targetPart:IsDescendantOf(Workspace) then
        toggleNoclip(true)

        local targetPos = targetPart.Position
        local dist = (targetPos - root.Position).Magnitude

        if Settings.FarmMode == "Instant TP" then
            root.CFrame = targetPart.CFrame
            root.AssemblyLinearVelocity = Vector3.zero
        else
            local tTime = math.clamp(dist / Settings.FarmSpeed, 0.04, 1.8)
            local tweenInfo = TweenInfo.new(tTime, Enum.EasingStyle.Linear)
            currentTween = TweenService:Create(root, tweenInfo, { CFrame = targetPart.CFrame })
            currentTween:Play()

            local startTween = tick()
            while currentTween and currentTween.PlaybackState == Enum.PlaybackState.Playing and (tick() - startTween) < (tTime + 0.05) do
                if (root.Position - targetPart.Position).Magnitude <= 3.2 then
                    break
                end
                task.wait(0.02)
            end

            if currentTween then
                currentTween:Cancel(); currentTween = nil
            end
        end

        local startGrab = tick()

        while targetPart and targetPart:IsDescendantOf(Workspace) and targetPart:IsDescendantOf(container) do
            if (tick() - startGrab) > 0.35 then
                ignoredCoins[targetPart] = tick() + 4.0
                break
            end

            root.CFrame = targetPart.CFrame
            root.AssemblyLinearVelocity = Vector3.zero
            touchCoin(targetPart, root)

            task.wait(0.02)

            if not targetPart.Parent or not targetPart:IsDescendantOf(container) then
                break
            end
        end

        ignoredCoins[targetPart] = tick() + 2.0
        if targetPart.Parent and targetPart.Parent ~= container then
            ignoredCoins[targetPart.Parent] = tick() + 2.0
        end

        if Settings.CoinDelay > 0 then
            task.wait(Settings.CoinDelay)
        end
    end
end

task.spawn(function()
    while true do
        task.wait(0.02)
        pcall(farmStep)
    end
end)

local function applySafeFarmPreset()
    Settings.FarmMode = "Tween"
    Settings.FarmSpeed = 22
    Settings.CoinDelay = 0.01
    Settings.MaxBagCapacity = 40
    Settings.ActionOnFull = "CombatWin"
    Settings.AvoidMurderer = true
    Settings.AvoidDistance = 35
    Settings.AvoidAction = "Kite"
    Settings.AutoHopAfterRound = false
    Settings.AutoGrabGun = false
    Settings.GunPriority = false
    Settings.AutoWinAsRoles = false
    Settings.ExtremeRAMSaver = true
    setAutoFarm(true)
    applyExtremeOptimization()
end

-- ==================== ВКЛАДКИ RAYFIELD ====================
if Window then
    local ok_ui, err_ui = pcall(function()
        local PresetsTab = Window:CreateTab("Presets", 0)
    local FarmTab = Window:CreateTab("Farm Settings", 0)
    local StatsTab = Window:CreateTab("Account Stats & Logs", 0)
    local CombatTab = Window:CreateTab("Combat", 0)
    local VisualsTab = Window:CreateTab("Visuals", 0)
    local MovementTab = Window:CreateTab("Movement", 0)
    local MiscTab = Window:CreateTab("Misc", 0)

    -- Presets
    PresetsTab:CreateSection("Quick Presets")

    PresetsTab:CreateButton({
        Name = "Safe Farm & Auto-Lobby Exit",
        Callback = function()
            applySafeFarmPreset()
            notifyUser("ym1co Preset", "Activated Safe Farm (22 studs/s) + Extra RAM", 3)
        end,
    })

    PresetsTab:CreateButton({
        Name = "Rage Farm",
        Callback = function()
            Settings.FarmMode = "Instant TP"
            Settings.FarmSpeed = 65
            Settings.CoinDelay = 0.01
            Settings.MaxBagCapacity = 40
            Settings.ActionOnFull = "CombatWin"
            Settings.AvoidMurderer = true
            setAutoFarm(true)
            notifyUser("ym1co Preset", "Activated Rage Farm", 3)
        end,
    })

    PresetsTab:CreateButton({
        Name = "AFK Night Farm",
        Callback = function()
            Settings.FarmMode = "Tween"
            Settings.FarmSpeed = 22
            Settings.CoinDelay = 0.01
            Settings.MaxBagCapacity = 40
            Settings.ActionOnFull = "Underground"
            Settings.AvoidMurderer = true
            Settings.AntiAFK = true
            setAutoFarm(true)
            notifyUser("ym1co Preset", "Activated AFK Night Farm (22 studs/s)", 3)
        end,
    })

    -- Farm Settings
    FarmTab:CreateSection("General")

    FarmTab:CreateToggle({
        Name = "Auto Farm",
        CurrentValue = true,
        Flag = "AutoFarmMain",
        Callback = function(Value)
            setAutoFarm(Value)
        end,
    })

    FarmTab:CreateSection("Speed and Movement")

    FarmTab:CreateSlider({
        Name = "Farm Speed (Safe: 20-25)",
        Range = { 10, 60 },
        Increment = 1,
        Suffix = " studs/s",
        CurrentValue = 22,
        Flag = "UserFarmSpeed",
        Callback = function(Value)
            Settings.FarmSpeed = Value
        end,
    })

    FarmTab:CreateSlider({
        Name = "Coin Delay",
        Range = { 0.01, 0.20 },
        Increment = 0.01,
        Suffix = " s",
        CurrentValue = 0.01,
        Flag = "UserCoinDelay",
        Callback = function(Value)
            Settings.CoinDelay = Value
        end,
    })

    FarmTab:CreateSlider({
        Name = "Bag Capacity",
        Range = { 10, 50 },
        Increment = 5,
        Suffix = " coins",
        CurrentValue = 40,
        Flag = "UserBagCap",
        Callback = function(Value)
            Settings.MaxBagCapacity = Value
        end,
    })

    FarmTab:CreateDropdown({
        Name = "Action on Full",
        Options = { "CombatWin", "Lobby", "Underground", "Server Hop" },
        CurrentOption = { "CombatWin" },
        MultipleOptions = false,
        Flag = "UserActionOnFull",
        Callback = function(Option)
            Settings.ActionOnFull = Option[1]
        end,
    })

    -- Populated Server Hunter
    FarmTab:CreateSection("Populated Server Hunter (8-20 Players)")

    FarmTab:CreateToggle({
        Name = "Hop after round if needed",
        CurrentValue = false,
        Flag = "UserAutoHopAfterRound",
        Callback = function(Value)
            Settings.AutoHopAfterRound = Value
        end,
    })

    -- Stats Tab (ТОЛЬКО УРОВЕНЬ И МЕШОК)
    StatsTab:CreateSection("Live Account Stats")

    local LiveStatsLabel = StatsTab:CreateParagraph({
        Title = "Account Information",
        Content = "Loading stats..."
    })

    task.spawn(function()
        while true do
            task.wait(2.0)
            pcall(function()
                local s = getAccountStats()
                LiveStatsLabel:Set({
                    Title = "User: " .. s.username .. " (ID: " .. s.userId .. ")",
                    Content = string.format("Level: %d\nBag: %d/%d", s.level, s.bag, s.maxBag)
                })
            end)
        end
    end)

    StatsTab:CreateSection("File Export Settings")

    StatsTab:CreateInput({
        Name = "Log File Name",
        PlaceholderText = "mm2_farm_stats.txt",
        RemoveTextAfterFocusLost = false,
        Callback = function(Text)
            if Text and Text:gsub("%s+", "") ~= "" then
                Settings.CustomLogFileName = Text
            end
        end,
    })

    StatsTab:CreateToggle({
        Name = "Auto Export to File",
        CurrentValue = true,
        Flag = "UserAutoExportStats",
        Callback = function(Value)
            Settings.AutoExportStats = Value
        end,
    })

    StatsTab:CreateSlider({
        Name = "Export Interval",
        Range = { 1, 60 },
        Increment = 1,
        Suffix = " sec",
        CurrentValue = 5,
        Flag = "UserExportInterval",
        Callback = function(Value)
            Settings.ExportInterval = Value
        end,
    })

    StatsTab:CreateButton({
        Name = "Save Stats Now (Экспорт вручную)",
        Callback = function()
            exportStatsToFile()
            notifyUser("Stats Logger", "Данные аккаунта экспортированы!", 3)
        end,
    })

    -- Combat Tab
    CombatTab:CreateSection("Murderer Evasion")

    CombatTab:CreateToggle({
        Name = "Avoid Murderer",
        CurrentValue = true,
        Flag = "UserAvoidMurderer",
        Callback = function(Value)
            Settings.AvoidMurderer = Value
        end,
    })

    CombatTab:CreateDropdown({
        Name = "Evasion Action",
        Options = { "Kite", "Underground" },
        CurrentOption = { "Kite" },
        MultipleOptions = false,
        Flag = "UserAvoidAction",
        Callback = function(Option)
            Settings.AvoidAction = Option[1]
        end,
    })

    CombatTab:CreateSection("Combat Automation")

    CombatTab:CreateToggle({
        Name = "Auto-Win when Full Bag",
        CurrentValue = true,
        Flag = "UserAutoWinRoles",
        Callback = function(Value)
            Settings.AutoWinAsRoles = Value
        end,
    })

    CombatTab:CreateToggle({
        Name = "Auto Grab Gun",
        CurrentValue = true,
        Flag = "UserAutoGrabGun",
        Callback = function(Value)
            Settings.AutoGrabGun = Value
        end,
    })

    -- Visuals Tab
    VisualsTab:CreateSection("HUD")

    VisualsTab:CreateToggle({
        Name = "Show HUD",
        CurrentValue = false,
        Flag = "UserShowHUD",
        Callback = function(Value)
            Settings.ShowHUD = Value
        end,
    })

    VisualsTab:CreateSection("Player ESP")

    local highlights = {}
    local function updateESP()
        for _, player in ipairs(Players:GetPlayers()) do
            if player ~= LocalPlayer and player.Character then
                local char = player.Character
                local hl = highlights[player] or char:FindFirstChild("ym1co_ESP")

                if not hl then
                    hl = Instance.new("Highlight")
                    hl.Name = "ym1co_ESP"
                    hl.Adornee = char
                    hl.Parent = char
                    highlights[player] = hl
                end

                local roles = getRoles()
                if player == roles.murderer then
                    hl.Enabled = Settings.ESP_Murderer
                    hl.FillColor = Color3.fromRGB(255, 35, 35)
                    hl.OutlineColor = Color3.fromRGB(255, 255, 255)
                elseif player == roles.sheriff then
                    hl.Enabled = Settings.ESP_Sheriff
                    hl.FillColor = Color3.fromRGB(40, 150, 255)
                    hl.OutlineColor = Color3.fromRGB(255, 255, 255)
                else
                    hl.Enabled = Settings.ESP_Innocents
                    hl.FillColor = Color3.fromRGB(60, 220, 70)
                    hl.OutlineColor = Color3.fromRGB(200, 200, 200)
                end
            end
        end
    end

    RunService.RenderStepped:Connect(function()
        pcall(updateESP)
    end)

    VisualsTab:CreateToggle({
        Name = "Murderer ESP",
        CurrentValue = true,
        Flag = "UserESPMurderer",
        Callback = function(Value)
            Settings.ESP_Murderer = Value
        end,
    })

    VisualsTab:CreateToggle({
        Name = "Sheriff ESP",
        CurrentValue = true,
        Flag = "UserESPSheriff",
        Callback = function(Value)
            Settings.ESP_Sheriff = Value
        end,
    })

    VisualsTab:CreateToggle({
        Name = "Innocent ESP",
        CurrentValue = false,
        Flag = "UserESPInnocents",
        Callback = function(Value)
            Settings.ESP_Innocents = Value
        end,
    })

    -- Movement Tab
    MovementTab:CreateSection("Movement")

    MovementTab:CreateToggle({
        Name = "Noclip",
        CurrentValue = true,
        Flag = "UserNoclip",
        Callback = function(Value)
            toggleNoclip(Value)
        end,
    })

    MovementTab:CreateSlider({
        Name = "WalkSpeed",
        Range = { 16, 120 },
        Increment = 2,
        CurrentValue = 16,
        Flag = "UserWalkSpeed",
        Callback = function(Value)
            Settings.WalkSpeed = Value
            local char = LocalPlayer.Character
            local hum = char and char:FindFirstChildWhichIsA("Humanoid")
            if hum then hum.WalkSpeed = Value end
        end,
    })

    MovementTab:CreateSlider({
        Name = "JumpPower",
        Range = { 50, 200 },
        Increment = 5,
        CurrentValue = 50,
        Flag = "UserJumpPower",
        Callback = function(Value)
            Settings.JumpPower = Value
            local char = LocalPlayer.Character
            local hum = char and char:FindFirstChildWhichIsA("Humanoid")
            if hum then hum.JumpPower = Value end
        end,
    })

    UserInputService.JumpRequest:Connect(function()
        if Settings.InfJump then
            local char = LocalPlayer.Character
            local hum = char and char:FindFirstChildWhichIsA("Humanoid")
            if hum then hum:ChangeState(Enum.HumanoidStateType.Jumping) end
        end
    end)

    MovementTab:CreateToggle({
        Name = "Infinite Jump",
        CurrentValue = false,
        Flag = "UserInfJump",
        Callback = function(Value)
            Settings.InfJump = Value
        end,
    })

    -- Misc Tab
    MiscTab:CreateSection("Farm & RAM Optimization")

    MiscTab:CreateToggle({
        Name = "Extreme RAM Saver (No 3D)",
        CurrentValue = true,
        Flag = "UserExtremeRAM",
        Callback = function(Value)
            Settings.ExtremeRAMSaver = Value
            if Value then
                applyExtremeOptimization()
            else
                pcall(function() RunService:Set3dRenderingEnabled(true) end)
            end
        end,
    })

    MiscTab:CreateButton({
        Name = "Hop to Populated Server (8-20 plrs)",
        Callback = function()
            hopToPopulatedServer(true)
        end,
    })

    MiscTab:CreateButton({
        Name = "Rejoin Server",
        Callback = function()
            TeleportService:TeleportToPlaceInstance(game.PlaceId, game.JobId, LocalPlayer)
        end,
    })

    Rayfield:LoadConfiguration()
    -- Автоматическое применение пресета Safe Farm + Extra RAM
    applySafeFarmPreset()
    end)
    if not ok_ui then
        warn("[ym1co UI] Rayfield UI build warning:", tostring(err_ui))
    end
end

-- Старт
applySafeFarmPreset()

notifyUser("ym1co farmer 5.0", "ym1co farmer 5.0: Preset & Extra RAM auto-activated!", 3)
