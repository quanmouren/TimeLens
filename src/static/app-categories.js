(function () {
    const CATEGORY_RULES = [
        {
            id: 'productivity',
            keywords: [
                'codex', 'trae', 'code', 'vscode', 'visual studio', 'cursor',
                'pycharm', 'idea', 'webstorm', 'terminal', 'powershell', 'cmd',
                'windows terminal', 'photoshop', 'illustrator', 'figma',
                'word', 'excel', 'powerpoint', 'wps', 'onenote', 'notepad',
                'obsidian', 'typora', 'notion',
            ],
        },
        {
            id: 'common',
            keywords: [
                'msedge', 'edge', 'chrome', 'firefox', 'safari', 'wechat',
                'weixin', 'qq', 'telegram', 'discord', 'explorer', 'settings',
                'photos', 'snippingtool', 'taskmgr', 'everything',
            ],
        },
        {
            id: 'other',
            keywords: [
                'steam', 'epic', 'bilibili', 'douyin', 'netease', 'cloudmusic',
                'spotify', 'potplayer', 'vlc', 'game', 'launcher',
            ],
        },
    ];

    function getAppCategory(app) {
        const text = `${app.app_name || ''} ${app.process_name || ''}`.toLowerCase();
        for (const rule of CATEGORY_RULES) {
            if (rule.keywords.some(keyword => text.includes(keyword))) {
                return rule.id;
            }
        }
        return 'other';
    }

    window.TimeLensCategories = {
        rules: CATEGORY_RULES,
        getAppCategory,
    };
}());
