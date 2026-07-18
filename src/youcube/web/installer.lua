--[[
_ _  _ ____ ___ ____ _    _    ____ ____
| |\ | [__   |  |__| |    |    |___ |__/
| | \| ___]  |  |  | |___ |___ |___ |  \

Github Repository: https://github.com/CC-YouCube
Homepage: https://youcube.madefor.cc/
License: GPL-3.0
]]
-- OpenInstaller v1.0.1 (based on wget)

local BASE_URL = "https://raw.githubusercontent.com/YC-Fork/YC-Client-Fork/main/src/"

local files = {
    ["./yc-fork-client.lua"] = BASE_URL .. "yc-fork-client.lua",
    ["./Yc-Fork-Client-Libs/serverapi.lua"] = BASE_URL .. "Yc-Fork-Client-Libs/serverapi.lua",
    ["./Yc-Fork-Client-Libs/numberformatter.lua"] = BASE_URL .. "Yc-Fork-Client-Libs/numberformatter.lua",
    ["./Yc-Fork-Client-Libs/semver.lua"] = BASE_URL .. "Yc-Fork-Client-Libs/semver.lua",
    ["./Yc-Fork-Client-Libs/argparse.lua"] = BASE_URL .. "Yc-Fork-Client-Libs/argparse.lua",
    ["./Yc-Fork-Client-Libs/string_pack.lua"] = BASE_URL .. "Yc-Fork-Client-Libs/string_pack.lua",
    ["./Yc-Fork-Client-Libs/uninstall.lua"] = BASE_URL .. "Yc-Fork-Client-Libs/uninstall.lua",
}

if not http then
    printError("OpenInstaller requires the http API")
    printError("Set http.enabled to true in the ComputerCraft config")
    return
end

local unknown_error = "Unknown error"

local function http_get(url)
    local valid_url, error_message = http.checkURL(url)
    if not valid_url then
        printError(('"%s" %s.'):format(url, error_message or "Invalid URL"))
        return
    end

    local response, http_error_message = http.get(url, nil, true)
    if not response then
        printError(('Failed to download "%s" (%s).'):format(url, http_error_message or unknown_error))
        return
    end

    local response_body = response.readAll()
    response.close()

    if not response_body then
        printError(('Failed to download "%s" (Empty response).'):format(url))
    end

    return response_body
end

for path, download_url in pairs(files) do
    local resolved_path = shell.resolve(path)

    -- Create directory if it doesn't exist
    local dir = fs.getDir(resolved_path)
    if not fs.exists(dir) then
        fs.makeDir(dir)
    end

    local response_body = http_get(download_url)
    if response_body then
        local file, file_open_error_message = fs.open(resolved_path, "wb")
        if not file then
            printError(('Failed to save "%s" (%s).'):format(path, file_open_error_message or unknown_error))
        else
            file.write(response_body)
            file.close()
            term.setTextColor(colors.lime)
            print(('Downloaded "%s"'):format(path))
            term.setTextColor(colors.white)
        end
    end
end

print("Installation/Update complete!")

write("Do you want to add a startup file? (y/N): ")
local input = read()
if input and (input:lower() == "y" or input:lower() == "yes") then
    local file, err = fs.open("/startup.lua", "w")
    if file then
        file.write('shell.run("yc-fork-client")\n')
        file.close()
        term.setTextColor(colors.lime)
        print("Created /startup.lua!")
        term.setTextColor(colors.white)
    else
        printError("Failed to create /startup.lua: " .. (err or "unknown error"))
    end
end