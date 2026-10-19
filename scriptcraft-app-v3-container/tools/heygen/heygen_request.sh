#!/bin/bash

curl --location 'https://api.heygen.com/v2/template/92c09f8e9a1c4f078f7ae53886b7ad80/generate' \
     --header "X-Api-Key: ${HEYGEN_API_KEY}" \
     --header 'Content-Type: application/json' \
     --data '{
  "caption": false,
  "title": "AI at the Beach - You're Bringing AI to the Beach — And That Changes Everything",
  "variables": {
    "first_name": {
      "name": "first_name",
      "type": "text",
      "properties": {
        "content": "I went to the beach to unplug — and a drone nearly stole that quiet moment by saving someone before a lifeguard spotted them. It'\''s not a Hollywood scene — it'\''s what pilots at a few beaches are already proving: cameras and on-board AI are shaving critical seconds off rescue times. Here'\''s the headline: in some trials, AI-assisted systems have cut emergency response times by as much as thirty percent. That'\''s not just a stat — that'\''s people getting help faster. Over the next few minutes you'\''ll get three practical takeaways. One: how AI actually \"sees\" the shore — the computer-vision and edge systems that point out swimmers, trash, or nests. Two: how that sight becomes action — alerts, drones that drop flotation devices, and rip-current warnings that show up on apps and signs. Three: easy ways you can use or test these tools today — from cleanup apps to tide-aware trip planners. Quick orientation: when I say \"AI at the beach\" I'\''m not talking about vaporware. I'\''m talking about concrete tech working together — on-device vision models on drones and towers, local sensor networks that fuse wave and buoy data, and wider remote sensing for things like oil sheens. On the consumer side, chat-based planners and AR overlays are already knitting those data sources into things you can actually use. Small, concrete pictures: a drone'\''s model flags an irregular swimmer pattern and sends exact GPS to a lifeguard'\''s wrist; a volunteer snaps foam on the sand and an app flags it as plastic and pins a cleanup hotspot; a chat planner builds a family-friendly beach itinerary that matches tide tables and parking. Last summer, in one coastal pilot, an autonomous drone flagged erratic movement, an alert went out, and a lifeguard intercepted — rescued, no major injury. That \"what-if turned real\" is the frame we'\''ll use to think through trade-offs: speed versus privacy, automation versus human judgment. Okay — next, we zoom in on \"seeing\": how computer vision identifies people, trash, and turtles along the shore."
      }
    }
  }
}'
