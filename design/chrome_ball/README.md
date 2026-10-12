# ClipMaker Chrome Football

- `cm-chrome-football.blend`: editable model, materials, camera and studio lights.
- `cm-chrome-football.glb`: compact application asset with silver and green PBR materials.
- `chrome-football-preview.png`: transparent 1200 x 1200 studio render.
- `create_chrome_ball.py`: reproducible Blender generation script.

The raised mark reads CM with a superscript 1.3, using Bahnschrift outlines.
The GLB contains geometry and materials only, without bitmap textures or lights.
Use a neutral studio environment map when displaying it in Three.js; reflections
are necessary for the chrome finish. The ball is centered at the origin, with a
radius of one unit. In the GLB the lettering faces positive Z.

Rebuild on Windows with Blender and the installed Bahnschrift font:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --python design/chrome_ball/create_chrome_ball.py
```
