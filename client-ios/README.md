# 智购罗盘 CartCompass iOS

Native SwiftUI client for the ecommerce guide challenge.

## Generate and Run

```bash
cd client-ios
xcodegen generate
open ShopGuide.xcodeproj
```

The app display name is 智购罗盘. The committed Xcode project is still
`ShopGuide.xcodeproj` for source-path compatibility, and it defaults to
`http://127.0.0.1:8000`. To point a debug build at another
backend, update `SHOPGUIDE_API_BASE_URL` in `project.yml` and run
`xcodegen generate`, or set `shopguide.apiBaseURL` in `UserDefaults` during
local debugging.
