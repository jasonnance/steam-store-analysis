DROP TABLE IF EXISTS game CASCADE;

CREATE TABLE game (
    steam_app_id int,
    game_name text,

    CONSTRAINT game_pk PRIMARY KEY (steam_app_id)
);

DROP TABLE IF EXISTS game_crawl CASCADE;

CREATE TABLE game_crawl (
    steam_app_id int,
    crawl_time timestamp with time zone DEFAULT (now() at time zone 'utc'),
    game_name text,
    short_description text,
    is_dlc boolean,
    reviews_last_30_days int,
    pct_positive_reviews_last_30_days real,
    reviews_all_time int,
    pct_positive_reviews_all_time real,
    release_date date,
    title text,
    developer text,
    publisher text,
    num_achievements int,
    full_price real,
    long_description text,
    metacritic_score int,

    CONSTRAINT game_crawl_pk PRIMARY KEY (steam_app_id, crawl_time),
    CONSTRAINT game_game_crawl_fk FOREIGN KEY (steam_app_id)
        REFERENCES game (steam_app_id)
);

DROP TABLE IF EXISTS steam_genre CASCADE;

CREATE TABLE steam_genre (
    genre_id serial,
    descr text,

    CONSTRAINT steam_genre_pk PRIMARY KEY (genre_id),
    CONSTRAINT steam_genre_descr_uniq UNIQUE (descr)
);

DROP TABLE IF EXISTS game_crawl_genre CASCADE;

CREATE TABLE game_crawl_genre (
    steam_app_id int,
    crawl_time timestamp with time zone,
    genre_id int,

    CONSTRAINT game_crawl_genre_pk PRIMARY KEY (steam_app_id, crawl_time, genre_id),
    CONSTRAINT game_crawl_game_crawl_genre_fk FOREIGN KEY (steam_app_id, crawl_time)
        REFERENCES game_crawl (steam_app_id, crawl_time) ON DELETE CASCADE,
    CONSTRAINT steam_genre_game_crawl_genre_fk FOREIGN KEY (genre_id)
        REFERENCES steam_genre (genre_id)
);

DROP TABLE IF EXISTS steam_tag CASCADE;

CREATE TABLE steam_tag (
    tag_id serial,
    descr text,

    CONSTRAINT steam_tag_pk PRIMARY KEY (tag_id),
    CONSTRAINT steam_tag_descr_uniq UNIQUE (descr)
);

DROP TABLE IF EXISTS game_crawl_tag CASCADE;

CREATE TABLE game_crawl_tag (
    steam_app_id int,
    crawl_time timestamp with time zone,
    tag_id int,

    CONSTRAINT game_crawl_tag_pk PRIMARY KEY (steam_app_id, crawl_time, tag_id),
    CONSTRAINT game_crawl_game_crawl_tag_fk FOREIGN KEY (steam_app_id, crawl_time)
        REFERENCES game_crawl (steam_app_id, crawl_time) ON DELETE CASCADE,
    CONSTRAINT steam_tag_game_crawl_tag_fk FOREIGN KEY (tag_id)
        REFERENCES steam_tag (tag_id)
);

DROP TABLE IF EXISTS steam_game_detail CASCADE;

CREATE TABLE steam_game_detail (
     detail_id serial,
     descr text,

    CONSTRAINT steam_game_detail_pk PRIMARY KEY (detail_id),
    CONSTRAINT steam_game_detail_descr_uniq UNIQUE (descr)
);

DROP TABLE IF EXISTS game_crawl_detail CASCADE;

CREATE TABLE game_crawl_detail (
    steam_app_id int,
    crawl_time timestamp with time zone,
    detail_id int,

    CONSTRAINT game_crawl_detail_pk PRIMARY KEY (steam_app_id, crawl_time, detail_id),
    CONSTRAINT game_crawl_game_crawl_detail_fk FOREIGN KEY (steam_app_id, crawl_time)
        REFERENCES game_crawl (steam_app_id, crawl_time) ON DELETE CASCADE,
    CONSTRAINT steam_game_detail_game_crawl_detail_fk FOREIGN KEY (detail_id)
        REFERENCES steam_game_detail (detail_id)
);

DROP VIEW IF EXISTS game_crawl_view CASCADE;

CREATE VIEW game_crawl_view AS
WITH game_genres AS (
  SELECT gcg.steam_app_id, array_agg(sg.descr) AS genres
  FROM game_crawl_genre gcg
    JOIN steam_genre sg
      USING (genre_id)
  GROUP BY gcg.steam_app_id
), game_details AS (
  SELECT gcd.steam_app_id, array_agg(sgd.descr) AS details
  FROM game_crawl_detail gcd
    JOIN steam_game_detail sgd
      USING (detail_id)
  GROUP BY gcd.steam_app_id
), game_tags AS (
  SELECT gct.steam_app_id, array_agg(st.descr) AS tags
  FROM game_crawl_tag gct
    JOIN steam_tag st
      USING (tag_id)
  GROUP BY gct.steam_app_id
)
SELECT
  gc.*,
  gg.genres,
  gd.details,
  gt.tags
FROM
  game_crawl gc
    LEFT JOIN game_genres gg
      USING (steam_app_id)
    LEFT JOIN game_details gd
      USING (steam_app_id)
    LEFT JOIN game_tags gt
      USING (steam_app_id);
