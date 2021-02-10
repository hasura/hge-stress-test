#!/usr/bin/env python
import random
import sys

def gen_tag(n):
    on_conflict = "on_conflict: { constraint: tags_name_key update_columns: [desc] }"
    return f"""
      {{ tag: 
        {{ 
          data: 
            {{ 
                name: "{n}" 
                desc: "{random.random()}" 
            }} 
          {on_conflict} 
        }}
      }}
    """

def gen_post(user_id, slug, tag_start, tag_end):
    tags = "[\n"
    for i in range(tag_start, tag_end):
        tags += gen_tag(i) + "\n"
    tags += "]"
    return f"""
      {{ 
        slug: "{slug}" 
        content: "{random.random()}" 
        user_id: {user_id} 
        post_tags: {{ data: {tags} }} 
      }}
    """

def gen_mut():
    tags_per_post = int(sys.argv[1])
    num_posts = int(sys.argv[2])

    slug_start = 0
    slug_end = num_posts

    posts = "[\n"
    for i in range(slug_start, slug_end):
        posts += gen_post(2, i, i * tags_per_post, (i + 1) * tags_per_post) + "\n"
    posts += "]"

    on_conflict = "on_conflict: { constraint: posts_slug_key update_columns: [content] }"
    return f"""
        mutation InsertBulk {{
          insert_posts(
            objects: {posts}
            {on_conflict}
          ) {{
            affected_rows
            returning {{
              id
              content
              post_tags {{
                id
                tag {{
                  id
                  name
                  desc
                }}
              }}
            }}
          }}
        }}"""

if __name__ == "__main__":
    print(gen_mut())
