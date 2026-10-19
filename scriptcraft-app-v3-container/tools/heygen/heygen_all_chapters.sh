#!/bin/bash
# HeyGen API curl commands - Generated from script
# Script: Direct Video - AI at the beach
# Generated: AI_at_the_beach_20251017_120929

# Chapter 1: Direct Video - AI at the beach
curl --location 'https://api.heygen.com/v2/template/92c09f8e9a1c4f078f7ae53886b7ad80/generate' \
     --header "X-Api-Key: ${HEYGEN_API_KEY}" \
     --header 'Content-Type: application/json' \
     --data '{
  "caption": false,
  "title": "Direct Video - AI at the beach",
  "variables": {
    "first_name": {
      "name": "first_name",
      "type": "text",
      "properties": {
        "content": "I went to the beach to unplug — and a drone nearly stole that quiet moment by saving someone before a lifeguard spotted them. It'\''s not a Hollywood scene — it'\''s what pilots at a few beaches are already proving: cameras and on-board AI are shaving critical seconds off rescue times. Here’s the headline: in some trials, AI-assisted systems have cut emergency response times by as much as thirty percent. That’s not just a stat — that'\''s people getting help faster. Over the next few minutes you'\''ll get three practical takeaways. One: how AI actually “sees” the shore — the computer-vision and edge systems that point out swimmers, trash, or nests. Two: how that sight becomes action — alerts, drones that drop flotation devices, and rip-current warnings that show up on apps and signs. Three: easy ways you can use or test these tools today — from cleanup apps to tide-aware trip planners. Quick orientation: when I say "AI at the beach" I'\''m not talking about vaporware. I'\''m talking about concrete tech working together — on-device vision models on drones and towers, local sensor networks that fuse wave and buoy data, and wider remote sensing for things like oil sheens. On the consumer side, chat-based planners and AR overlays are already knitting those data sources into things you can actually use. Small, concrete pictures: a drone'\''s model flags an irregular swimmer pattern and sends exact GPS to a lifeguard'\''s wrist; a volunteer snaps foam on the sand and an app flags it as plastic and pins a cleanup hotspot; a chat planner builds a family-friendly beach itinerary that matches tide tables and parking. Last summer, in one coastal pilot, an autonomous drone flagged erratic movement, an alert went out, and a lifeguard intercepted — rescued, no major injury. That “what-if turned real” is the frame we'\''ll use to think through trade-offs: speed versus privacy, automation versus human judgment. Okay — next, we zoom in on "seeing": how computer vision identifies people, trash, and turtles along the shore."
      }
    }
  }
}'


# Chapter 2: Direct Video - AI at the beach - How AI Sees the Shoreline — Detection, Segmentation, and ID
curl --location 'https://api.heygen.com/v2/template/92c09f8e9a1c4f078f7ae53886b7ad80/generate' \
     --header "X-Api-Key: ${HEYGEN_API_KEY}" \
     --header 'Content-Type: application/json' \
     --data '{
  "caption": false,
  "title": "Direct Video - AI at the beach - How AI Sees the Shoreline — Detection, Segmentation, and ID",
  "variables": {
    "first_name": {
      "name": "first_name",
      "type": "text",
      "properties": {
        "content": "We just talked about drones and sensors pointing out trouble — now let’s look under the hood at how they actually "see." There are three practical computer-vision moves you should know: detection, segmentation, and classification. Each gives the system a different kind of situational awareness. Start with detection. That’s the job that draws the box. On live video, lightweight detectors scan frames and flag objects of interest — swimmers, surfboards, even a floating cooler — and attach a confidence score. Engineers often use fast families of detectors for this; the point isn’t the name, it’s the function: quick, approximate localization that can run on a drone in real time. Next up, segmentation. If detection says "there’s something here," segmentation says exactly which pixels belong to it. That pixel-level mask is what helps systems tell plastic from kelp or map the exact edge of a turtle nest. For cleanups, that detail matters: a heatmap built from segmentation gives crews a precise route instead of a guess. And classification is the ID step — the model answers "what is it?" From a close-up photo, a classifier can say "loggerhead hatchling" or "single-use plastic bottle." That’s how volunteers use apps to upload a photo and get a reliable ID and recommended action: monitor, mark, or alert authorities. Here’s a concrete scene: a volunteer on dusk patrol snaps a fuzzy photo near the dunes. Seconds later the app replies: "Loggerhead hatchling — likely fresh; coordinates sent to conservation team." Volunteers rope off the area and trampling is avoided. That tiny feedback loop changes behavior. But it’s not flawless. Sun glare, foam, swimmers half-submerged, or overlapping people can confuse detectors. Models trained on sunny, sandy beaches may struggle on rocky, foggy coasts — that’s dataset bias in the wild. Micro-features like wet towels or dark rocks can look like swimmers in low light. So most systems use human-in-the-loop verification: the AI flags a candidate and a lifeguard or volunteer confirms before any critical action. Teams also fine-tune general vision models on beach-specific images to cut false alarms — transfer learning, basically teaching a model the local language of sand, surf, and seaweed. And when the model is uncertain, robust deployments require redundancy: multiple cameras, a confirming buoy sensor, or a second drone pass. Bottom line: detection, segmentation, and classification give us boxes, masks, and labels — the raw awareness. But awareness only matters when it becomes action. Next, we’ll show how those detections get turned into real-world responses: alerts, drone drops, and faster lifeguard decisions."
      }
    }
  }
}'


# Chapter 3: Direct Video - AI at the beach - See → Act: Turning Detection into Rescue
curl --location 'https://api.heygen.com/v2/template/92c09f8e9a1c4f078f7ae53886b7ad80/generate' \
     --header "X-Api-Key: ${HEYGEN_API_KEY}" \
     --header 'Content-Type: application/json' \
     --data '{
  "caption": false,
  "title": "Direct Video - AI at the beach - See → Act: Turning Detection into Rescue",
  "variables": {
    "first_name": {
      "name": "first_name",
      "type": "text",
      "properties": {
        "content": "So we know AI can point out a person, plastic, or a nest — but spotting something doesn'\''t save anyone by itself. Seeing is just the first step. The real work is closing the loop quickly so that a flag on a screen becomes the right action on the sand. Think of it like a smoke detector. It can sense smoke all day, but if it never sounds the alarm, nobody moves. On beaches, that alarm needs to be fast, reliable, and precise — seconds matter in a rip or a sudden medical emergency. There are three things you need to wire together for that to happen. First: fast local detection. Models run right on the drone or camera so alerts happen in seconds, not minutes. The goal is tiny, efficient models that flag an unusual pattern and send a short clip or coordinates — not a constant stream of full-resolution video to the cloud. That keeps latency low and bandwidth costs manageable. Second: confirmation and redundancy. False alarms are dangerous — they erode trust. Good systems fuse multiple signals: a visual hit plus a buoy'\''s wave sensor, or two drone passes, or a human glance on a lifeguard tablet. That cross-check reduces mistakes and makes the system usable in the real world. Third: action pathways. Once something is confirmed, smart systems do several things at once: they ping the nearest lifeguard with exact GPS, they can dispatch a drone capable of dropping a flotation device, and they push a geo-fenced alert to nearby phones or digital signs saying "Avoid this zone — response in progress." The faster and more coordinated those steps, the better the outcome. Rip-current detection shows how prediction meets action. Models combine shore-camera imagery, buoy telemetry, and weather forecasts to create short-term risk maps. Instead of a vague "rips possible today," you get location-specific warnings: "Avoid this 200-meter stretch for the next 30 minutes." Those targeted warnings actually change behavior — and that'\''s the point. There are practical constraints. Many beaches have spotty networks, so systems are built to work offline when needed — local mesh networks, radio links, or occasional satellite uplinks. Human verification stays in the loop for anything critical. And privacy matters: responsible deployments blur faces, store minimal footage, and only keep identifiable data when there'\''s a validated incident. What this means for you: sign up for local beach alerts if they exist, treat digital warnings like a lifeguard'\''s whistle, and ask your parks department whether they run pilot systems — community oversight is how these tools stay accountable. One quick question for you — would you trust a drone to watch you swim if it meant faster rescues? Drop a yes or no in the comments and tell us why. Next, we'\''ll look at the hardware and scenarios that make this happen — drones that drop flotation, rip-detection systems, and the alerts that reach your phone."
      }
    }
  }
}'


# Chapter 4: Direct Video - AI at the beach - Saving Lives — Drones, Rip Warnings, and Real-Time Alerts
curl --location 'https://api.heygen.com/v2/template/92c09f8e9a1c4f078f7ae53886b7ad80/generate' \
     --header "X-Api-Key: ${HEYGEN_API_KEY}" \
     --header 'Content-Type: application/json' \
     --data '{
  "caption": false,
  "title": "Direct Video - AI at the beach - Saving Lives — Drones, Rip Warnings, and Real-Time Alerts",
  "variables": {
    "first_name": {
      "name": "first_name",
      "type": "text",
      "properties": {
        "content": "We just covered how systems spot swimmers and trash. Now let’s follow that signal into action — the actual life-saving stuff. Picture a drone scanning the surf. An onboard model flags an odd motion, the system estimates distance, and an alert fires. That alert can do three things at once: ping the nearest lifeguard with GPS, dispatch a drone that drops a flotation device, and push a geo-targeted notice to phones or a digital sign. In pilot runs, those combined steps shave off critical seconds — sometimes a minute or more — and in this business, a minute often changes the outcome. How does this work in practice? Cameras and drones capture continuous footage by day and sometimes thermal at night. Compact models running on the device spot likely distress patterns and send short clips or coordinates instead of streaming raw video. Low-latency links relay the essentials to a lifeguard console. Simple decision rules prevent spamming false alarms, and human verification sits at the end of the chain for any rescue. Rip-current detection is a different but equally important piece. It mixes repeated imagery, buoy telemetry, and weather data to find likely rip channels — those narrow bands of fast water heading offshore. The result is short-term, location-specific risk maps that feed apps, digital signs, and lifeguard dashboards: not "rips possible today," but "avoid this 200-meter stretch for the next 30 minutes." That precision actually changes behavior. There are real limits. Batteries die, networks are spotty on remote beaches, glare and crowds create false positives, and models trained in one region may underperform in another. That’s why redundancy — multiple sensors, second drone passes, lifeguard confirmation — and clear privacy rules are standard in responsible deployments. What you can do: enable local beach alerts if available, take phone warnings seriously, and ask your parks department whether they run pilot systems and what their privacy rules are. Those small steps help these systems be effective and accountable. Next up: how AI helps clean coastlines — spotting plastic, oil, and habitat damage — and how volunteers turn photos into real cleanup maps."
      }
    }
  }
}'


# Chapter 5: Direct Video - AI at the beach - Cleaner Coasts — How AI Finds Plastic, Oil, and Habitat Damage
curl --location 'https://api.heygen.com/v2/template/92c09f8e9a1c4f078f7ae53886b7ad80/generate' \
     --header "X-Api-Key: ${HEYGEN_API_KEY}" \
     --header 'Content-Type: application/json' \
     --data '{
  "caption": false,
  "title": "Direct Video - AI at the beach - Cleaner Coasts — How AI Finds Plastic, Oil, and Habitat Damage",
  "variables": {
    "first_name": {
      "name": "first_name",
      "type": "text",
      "properties": {
        "content": "We saw how AI helps save lives — now let’s talk about cleaning the shore. AI isn’t a magic vacuum; it’s a better set of eyes and a smarter map. That combination makes cleanups faster and more targeted. There are three main data streams here. First: satellites give broad, repeat coverage — they spot big events like oil sheens or large algal blooms and can cover hundreds of miles quickly. Second: drones and boat-mounted cameras give high-resolution close-ups where models can actually flag floating bags, nets, or clusters of bottles. Third: crowdsourced phone photos plug the gaps on the beach — volunteers’ geotagged snaps are gold for pinpointing hotspots. What the models do is practical. They’re trained on labeled images so they learn visual patterns — color, texture, and shape — that distinguish plastic from seaweed or sheen from waves. On boats and drones, fast detectors mark coordinates and feed heatmaps to crews. On shore, segmentation tools can outline plastic in a photo so cleanup teams know exactly where to search. A quick real-world example: a small crew runs a camera off their boat, an onboard detector flags a patch of floating debris, GPS coordinates are logged, and the team sails straight to it. In pilot runs, crews using these heatmaps covered twice as much polluted area in the same time compared to random searching. Satellites, meanwhile, can trigger faster response after a tanker incident by sending automated alerts to response teams. But there are limits. Turbid water, whitecaps, and foam can trigger false positives. Microplastics are too small to see from the air — those still need sampling. So human verification is essential: people validate detections, improve training data, and reduce mistakes over time. The community angle is powerful. Cleanup apps let volunteers upload geotagged photos, tag items, and aggregate reports into maps. The app can triage — “urgent: fishing net” vs. “medium: single-use plastic” — and route jobs to volunteers or waste services. A few quick tips to help the models: take photos mid-morning with the sun behind you for better contrast, include a common object for scale, and keep location services on when you snap the image. There are also governance questions we can’t ignore: who owns location data, how long is imagery stored, and how do we prevent surveillance of vulnerable communities? Those are serious and solvable issues — insist on transparency, short retention windows, and community oversight when projects roll out. If you want to help right now: download a local cleanup app, start tagging finds, or join a mapped cleanup event. Small images and simple labels add up — they let AI turn scattered reports into smarter routes that actually remove trash and protect habitats. Next, we’ll switch gears to the consumer side — how AI can supercharge your beach day with trip planning, AR overlays, and photo tools."
      }
    }
  }
}'


# Chapter 6: Direct Video - AI at the beach - Your Beach Day, Supercharged — Trip Planning, AR Safety, and Photo AI
curl --location 'https://api.heygen.com/v2/template/92c09f8e9a1c4f078f7ae53886b7ad80/generate' \
     --header "X-Api-Key: ${HEYGEN_API_KEY}" \
     --header 'Content-Type: application/json' \
     --data '{
  "caption": false,
  "title": "Direct Video - AI at the beach - Your Beach Day, Supercharged — Trip Planning, AR Safety, and Photo AI",
  "variables": {
    "first_name": {
      "name": "first_name",
      "type": "text",
      "properties": {
        "content": "We just saw AI helping crews and conservationists — now let’s talk about what it does for your beach day. The same data that powers rescue and cleanup can also make your trip safer, less chaotic, and more photogenic. Start with trip planning. Instead of juggling tide charts and parking maps, ask a chat model to build a time-based plan. Try something like: "Plan a 6-hour family beach day for two adults and two kids (ages 6 and 9). Low tide around 3pm, parking within a 10-minute walk, and a shady lunch spot. Include a rain backup and a safety-first checklist." A good planner will pull tide info, suggest arrival times to avoid crowds, and spit out a quick packing list — sunscreen, shade, flotation, snacks, battery pack. Tip: the more constraints you give — "beginner swimmer" or "no stairs" — the better the result. Next, AR and micro-forecasting. Apps now layer localized wind, tide, and rip-risk data over your camera so you can point your phone at the water and see color bands: green = safe, yellow = caution, red = avoid. That overlay comes from buoy data, local cameras, and short-term wave models. It’s not perfect, but it gives immediate, location-specific context that a standard weather app won’t. AR also helps you find tide pools, mark protected areas, or show the best sunset ledge for photos — just respect habitat markers and don’t trample nesting sites. And if you see an AR marker for "protected zone," treat it like rope on the sand. Photography is where AI really shines for most people. Phones already merge exposures and reduce noise; layered on top of that are editing tools that can remove a photobomber, subtly boost golden highlights, or clean a small piece of trash from the foreground while preserving reflections. Quick workflow: lock exposure on the sky, take a burst, let the AI blend the best frames, then apply a light warmth boost and preserve natural skin tones. If you remove someone, use the app’s texture-aware healing so reflections in wet sand look real. A few quick, practical tips before we move on: 1) Download offline tide charts and maps for spotty signal locations. 2) Save the generated packing checklist to your phone — it beats a last-minute store run. 3) Turn on local beach alerts if available; treat digital warnings like a lifeguard whistle. 4) When using AR overlays, still look up and scan the water — AI helps, but it doesn’t replace judgment. All of this is already available in apps today — and over time these features will get more accurate and privacy-aware. Next, we'\''ll go under the hood: what sensors and edge models actually run those overlays and planners."
      }
    }
  }
}'


# Chapter 7: Direct Video - AI at the beach - Under the Hood — Sensors, Edge Models, and the Data Loop
curl --location 'https://api.heygen.com/v2/template/92c09f8e9a1c4f078f7ae53886b7ad80/generate' \
     --header "X-Api-Key: ${HEYGEN_API_KEY}" \
     --header 'Content-Type: application/json' \
     --data '{
  "caption": false,
  "title": "Direct Video - AI at the beach - Under the Hood — Sensors, Edge Models, and the Data Loop",
  "variables": {
    "first_name": {
      "name": "first_name",
      "type": "text",
      "properties": {
        "content": "We just saw how AI can make your day safer and cleaner. Now let’s pull back the curtain and see what actually runs those features — the sensors, the small models, and the data flow that ties everything together. Think of the system as a chain of lookouts. Cameras, buoys, and drones collect raw signals. Small models running right on those devices decide fast. Summaries and verified events get sent to the cloud for logging and analysis. Finally, dashboards, alerts, and people act. That flow — sensors → device models → cloud aggregation → human review — is what turns pixels into action. Why run models on the device? Speed and bandwidth. If a camera can flag a likely swimmer immediately, it can send a short clip or GPS instead of streaming full-resolution video all the time. That reduces delays and helps systems work where connectivity is weak. Many deployments are designed so raw video never leaves the device unless an incident is confirmed — that’s a practical privacy plus. Where does the training data come from? It’s a mix. Large general image datasets give models basic vision skills, and teams fine-tune them with beach-specific photos — drone footage, volunteers’ tagged trash pics, annotated turtle nests — so they learn local clues. Satellites and commercial imagery add wide-area views for oil or blooms, while buoys and weather feeds provide the ocean data that powers rip predictions. On the software side, engineers use transfer learning: start with a general vision model, then teach it the local language of sand, surf, and seaweed. On the hardware side, tiny chips and optimized software let those models run on drones and towers without a full data-center behind them. Now the messy part: limits and failure modes. Glare, foam, and crowded shorelines create false positives. A model trained on sunny, sandy beaches won’t automatically work well on foggy, rocky coasts — that’s dataset bias in the real world. Remote sites may have spotty networks, so systems must be built to operate offline and sync later. Models also drift as seasons and beach conditions change, so ongoing human labeling and retraining are essential. Human-in-the-loop is the secret sauce. A typical day looks like this: devices check status at dawn, an edge model flags a possible incident mid-morning, a drone gets a closer look, the lifeguard verifies the clip on a tablet, and flagged footage is reviewed later for model improvement. People close the loop; AI speeds the whole cycle. As a beachgoer, simple questions matter. When your local council talks about pilots, ask: is raw video stored or just metadata? Who owns the labeled data? Are alerts processed locally or sent to a central cloud? How long is location data retained? Those answers shape privacy, fairness, and who benefits. Bottom line: diverse sensors plus small, local models make these systems practical today — but they only work well with local tuning, human oversight, and clear policies. Next, we’ll wrap up with the ethical trade-offs, job impacts, and three practical actions you can take this week."
      }
    }
  }
}'


# Chapter 8: Direct Video - AI at the beach - What Comes Next — Ethics, Jobs, and Practical Takeaways
curl --location 'https://api.heygen.com/v2/template/92c09f8e9a1c4f078f7ae53886b7ad80/generate' \
     --header "X-Api-Key: ${HEYGEN_API_KEY}" \
     --header 'Content-Type: application/json' \
     --data '{
  "caption": false,
  "title": "Direct Video - AI at the beach - What Comes Next — Ethics, Jobs, and Practical Takeaways",
  "variables": {
    "first_name": {
      "name": "first_name",
      "type": "text",
      "properties": {
        "content": "We’ve covered how AI spots swimmers, maps trash, and helps plan your day. Now the real question: who controls this tech, who benefits, and what can you do? First — ethics and privacy. A camera that helps find a drowning person is clearly good. The same camera, left unchecked, can record families, cars, and patterns of where people go. That’s why pilots should come with simple, transparent rules: short retention windows, limited access, and clear opt-outs for sensitive areas like kids’ play zones. If your local park tries a program, ask for those specifics — don’t accept vague promises. Second — jobs and roles. AI doesn’t replace lifeguards so much as change what they do. Expect more drone operation, data checks, and decision-making around automated alerts. That opens new roles — drone technicians, data stewards, community auditors — and training in those skills is a real payoff for lifeguards and local hires. Third — accuracy and bias. Models make mistakes, and those mistakes can create unequal safety. A camera might miss a swimmer in low light or flag foam as a person. Demand transparency: what datasets were used? What’s the false-positive rate? How often are humans reviewing alerts? Community audits and third-party checks should be part of any rollout. Here are three things you can do this week: 1) Try one tool — download an AI beach planner or tide-aware app and note any privacy prompts. 2) Help improvement — join a cleanup app or upload geotagged photos; that data actually improves models. 3) Show up informed — bring these five questions to your next town meeting: - Who owns the footage? - How long is raw video and location data retained? - Is there a human-in-the-loop before any rescue action? - Who audits system performance and bias? - What opt-outs exist for sensitive zones? Looking ahead, expect better micro-forecasts, biodegradable sensors on buoys, and clearer AR safety layers in apps. That future can make beaches safer and cleaner — but only if communities insist on transparency, human oversight, and fair data. So don’t panic, and don’t passively accept tech. Use it, test it, and push for accountability. Drop one question you'\''d ask your local council in the comments — I’ll share templates you can copy and use at meetings."
      }
    }
  }
}'

