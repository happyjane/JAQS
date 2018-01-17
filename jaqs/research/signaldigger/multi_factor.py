# encoding=utf-8
from functools import reduce

from . import process
import pandas as pd
import numpy as np
from sklearn.covariance import LedoitWolf
import jaqs.util as jutil
from . import performance as pfm
from . import SignalCreator


# 因子间存在较强同质性时，使用施密特正交化方法对因子做正交化处理，用得到的正交化残差作为因子
def orthogonalize(factors_dict=None,
                  standardize_type="z_score",
                  winsorization=False,
                  index_member=None):
    """
    # 因子间存在较强同质性时，使用施密特正交化方法对因子做正交化处理，用得到的正交化残差作为因子
    :param index_member:
    :param factors_dict: 若干因子组成的字典(dict),形式为:
                         {"factor_name_1":factor_1,"factor_name_2":factor_2}
                       　每个因子值格式为一个pd.DataFrame，索引(index)为date,column为asset
    :param standardize_type: 标准化方法，有"rank"（排序标准化）,"z_score"(z-score标准化)两种（"rank"/"z_score"）
    :return: factors_dict（new) 正交化处理后所得的一系列新因子。
    """

    from scipy import linalg
    from functools import partial

    def Schmidt(data):
        return linalg.orth(data)

    def get_vector(date, factor):
        return factor.loc[date]

    if not factors_dict or len(list(factors_dict.keys())) < 2:
        raise ValueError("你需要给定至少２个因子")

    new_factors_dict = {}  # 用于记录正交化后的因子值
    for factor_name in factors_dict.keys():
        new_factors_dict[factor_name] = []
        # 处理非法值
        factors_dict[factor_name] = jutil.fillinf(factors_dict[factor_name])
        if winsorization:
            factors_dict[factor_name] = process.winsorize(factors_dict[factor_name], index_member=index_member)

    factor_name_list = list(factors_dict.keys())
    factor_value_list = list(factors_dict.values())
    # 施密特正交
    for date in factor_value_list[0].index:
        data = list(map(partial(get_vector, date), factor_value_list))
        data = pd.concat(data, axis=1, join="inner")
        if len(data) == 0:
            continue
        data = data.dropna()
        data = pd.DataFrame(Schmidt(data), index=data.index)
        data.columns = factor_name_list
        for factor_name in factor_name_list:
            row = pd.DataFrame(data[factor_name]).T
            row.index = [date, ]
            new_factors_dict[factor_name].append(row)

    # 因子标准化
    for factor_name in factor_name_list:
        factor_value = pd.concat(new_factors_dict[factor_name])
        if standardize_type == "z_score":
            new_factors_dict[factor_name] = process.standardize(factor_value, index_member)
        else:
            new_factors_dict[factor_name] = process.rank_standardize(factor_value, index_member)

    return new_factors_dict


# 获取因子的ic序列
def get_factors_ic_df(factors_dict,
                      price,
                      high=None,
                      low=None,
                      benchmark_price=None,
                      period=5,
                      quantiles=5,
                      mask=None,
                      can_enter=None,
                      can_exit=None,
                      commisson=0.0008,
                      forward=True,
                      ret_type="return",
                      **kwargs):
    """
    获取多个因子ic值序列矩阵
    :param factors_dict: 若干因子组成的字典(dict),形式为:
                         {"factor_name_1":factor_1,"factor_name_2":factor_2}
    :param pool: 股票池范围（list),如：["000001.SH","600300.SH",......]
    :param start: 起始时间 (int)
    :param end: 结束时间 (int)
    :param period: 指定持有周期(int)
    :param quantiles: 根据因子大小将股票池划分的分位数量(int)
    :param price : 包含了pool中所有股票的价格时间序列(pd.Dataframe)，索引（index)为datetime,columns为各股票代码，与pool对应。
    :param benchmark_price:基准收益，不为空计算相对收益，否则计算绝对收益
    :return: ic_df 多个因子ｉc值序列矩阵
             类型pd.Dataframe,索引（index）为datetime,columns为各因子名称，与factors_dict中的对应。
             如：

            　　　　　　　　　　　BP	　　　CFP	　　　EP	　　ILLIQUIDITY	REVS20	　　　SRMI	　　　VOL20
            date
            2016-06-24	0.165260	0.002198	0.085632	-0.078074	0.173832	0.214377	0.068445
            2016-06-27	0.165537	0.003583	0.063299	-0.048674	0.180890	0.202724	0.081748
            2016-06-28	0.135215	0.010403	0.059038	-0.034879	0.111691	0.122554	0.042489
            2016-06-29	0.068774	0.019848	0.058476	-0.049971	0.042805	0.053339	0.079592
            2016-06-30	0.039431	0.012271	0.037432	-0.027272	0.010902	0.077293	-0.050667
    """
    if ret_type is None:
        ret_type = "return"

    if not (ret_type in ["return", "upside_ret", "downside_ret"]):
        raise ValueError("不支持对%s收益的ic计算!支持的收益类型有return, upside_ret, downside_ret." % (ret_type,))

    ic_table = []
    sc = SignalCreator(
        price,
        high=high,
        low=low,
        benchmark_price=benchmark_price,
        period=period,
        n_quantiles=quantiles,
        mask=mask,
        can_enter=can_enter,
        can_exit=can_exit,
        forward=forward,
        commission=commisson
    )
    # 获取factor_value的时间（index）,将用来生成 factors_ic_df 的对应时间（index）
    times = sorted(
        pd.concat([pd.Series(factors_dict[factor_name].index) for factor_name in factors_dict.keys()]).unique())
    for factor_name in factors_dict.keys():
        factors_dict[factor_name] = jutil.fillinf(factors_dict[factor_name])
        factor_value = factors_dict[factor_name]
        signal_data = sc.get_signal_data(factor_value)
        if ret_type in signal_data.columns:
            signal_data = signal_data[["signal", ret_type]]
            signal_data.columns = ["signal", "return"]
            ic = pd.DataFrame(pfm.calc_signal_ic(signal_data))
            ic.columns = [factor_name, ]
            ic_table.append(ic)
        else:
            raise ValueError("signal_data中不包含%s收益,无法进行ic计算!" % (ret_type,))

    ic_df = pd.concat(ic_table, axis=1).dropna().reindex(times)

    return ic_df


# 根据样本协方差矩阵估算结果求最大化IC_IR下的多因子组合权重
def max_IR_weight(ic_df,
                  holding_period,
                  rollback_period=120,
                  covariance_type="shrink"):
    """
    输入ic_df(ic值序列矩阵),指定持有期和滚动窗口，给出相应的多因子组合权重
    :param ic_df: ic值序列矩阵 （pd.Dataframe），索引（index）为datetime,columns为各因子名称。
             如：

            　　　　　　　　　　　BP	　　　CFP	　　　EP	　　ILLIQUIDITY	REVS20	　　　SRMI	　　　VOL20
            date
            2016-06-24	0.165260	0.002198	0.085632	-0.078074	0.173832	0.214377	0.068445
            2016-06-27	0.165537	0.003583	0.063299	-0.048674	0.180890	0.202724	0.081748
            2016-06-28	0.135215	0.010403	0.059038	-0.034879	0.111691	0.122554	0.042489
            2016-06-29	0.068774	0.019848	0.058476	-0.049971	0.042805	0.053339	0.079592
            2016-06-30	0.039431	0.012271	0.037432	-0.027272	0.010902	0.077293	-0.050667

    :param holding_period: 持有周期(int)
    :param rollback_period: 滚动窗口，即计算每一天的因子权重时，使用了之前rollback_period下的IC时间序列来计算IC均值向量和IC协方差矩阵（int)。
    :param covariance_type:"shrink"/"simple" 协防差矩阵估算方式　Ledoit-Wolf压缩估计或简单估计
    :return: weight_df:使用Sample协方差矩阵估算方法得到的因子权重(pd.Dataframe),
             索引（index)为datetime,columns为待合成的因子名称。
    """
    n = rollback_period
    weight_df = pd.DataFrame(index=ic_df.index, columns=ic_df.columns)
    lw = LedoitWolf()
    for dt in ic_df.index:
        ic_dt = ic_df[ic_df.index <= dt].tail(n)
        if len(ic_dt) < n:
            continue
        if covariance_type == "shrink":
            try:
                ic_cov_mat = lw.fit(ic_dt.as_matrix()).covariance_
            except:
                ic_cov_mat = np.mat(np.cov(ic_dt.T.as_matrix()).astype(float))
        else:
            ic_cov_mat = np.mat(np.cov(ic_dt.T.as_matrix()).astype(float))
        inv_ic_cov_mat = np.linalg.inv(ic_cov_mat)
        weight = inv_ic_cov_mat * np.mat(ic_dt.mean().values).reshape(len(inv_ic_cov_mat), 1)
        weight = np.array(weight.reshape(len(weight), ))[0]
        weight_df.ix[dt] = weight / np.sum(weight)

    return weight_df.shift(holding_period)


# 根据样本协方差矩阵估算结果求最大化单期IC下的多因子组合权重
def max_IC_weight(ic_df,
                  factors_dict,
                  holding_period,
                  covariance_type="shrink"):
    """
    输入ic_df(ic值序列矩阵),指定持有期和滚动窗口，给出相应的多因子组合权重
    :param factors_dict: 若干因子组成的字典(dict),形式为:
                         {"factor_name_1":factor_1,"factor_name_2":factor_2}
                       　每个因子值格式为一个pd.DataFrame，索引(index)为date,column为asset
    :param ic_df: ic值序列矩阵 （pd.Dataframe），索引（index）为datetime,columns为各因子名称。
             如：

            　　　　　　　　　　　BP	　　　CFP	　　　EP	　　ILLIQUIDITY	REVS20	　　　SRMI	　　　VOL20
            date
            2016-06-24	0.165260	0.002198	0.085632	-0.078074	0.173832	0.214377	0.068445
            2016-06-27	0.165537	0.003583	0.063299	-0.048674	0.180890	0.202724	0.081748
            2016-06-28	0.135215	0.010403	0.059038	-0.034879	0.111691	0.122554	0.042489
            2016-06-29	0.068774	0.019848	0.058476	-0.049971	0.042805	0.053339	0.079592
            2016-06-30	0.039431	0.012271	0.037432	-0.027272	0.010902	0.077293	-0.050667

    :param holding_period: 持有周期(int)
    :param covariance_type:"shrink"/"simple" 协防差矩阵估算方式　Ledoit-Wolf压缩估计或简单估计
    :return: weight_df:使用Sample协方差矩阵估算方法得到的因子权重(pd.Dataframe),
             索引（index)为datetime,columns为待合成的因子名称。
    """
    weight_df = pd.DataFrame(index=ic_df.index, columns=ic_df.columns)
    lw = LedoitWolf()
    for dt in ic_df.index:
        f_dt = pd.concat([factors_dict[factor_name].loc[dt] for factor_name in ic_df.columns], axis=1).dropna()
        if len(f_dt) == 0:
            continue
        if covariance_type == "shrink":
            try:
                f_cov_mat = lw.fit(f_dt.as_matrix()).covariance_
            except:
                f_cov_mat = np.mat(np.cov(f_dt.T.as_matrix()).astype(float))
        else:
            f_cov_mat = np.mat(np.cov(f_dt.T.as_matrix()).astype(float))
        inv_f_cov_mat = np.linalg.inv(f_cov_mat)
        weight = inv_f_cov_mat * np.mat(ic_df.loc[dt].values).reshape(len(inv_f_cov_mat), 1)
        weight = np.array(weight.reshape(len(weight), ))[0]
        weight_df.ix[dt] = weight / np.sum(weight)

    return weight_df.shift(holding_period)


# 以IC为多因子组合权重
def ic_weight(ic_df,
              holding_period,
              rollback_period=120):
    """
    输入ic_df(ic值序列矩阵),指定持有期和滚动窗口，给出相应的多因子组合权重
    :param ic_df: ic值序列矩阵 （pd.Dataframe），索引（index）为datetime,columns为各因子名称。
             如：

            　　　　　　　　　　　BP	　　　CFP	　　　EP	　　ILLIQUIDITY	REVS20	　　　SRMI	　　　VOL20
            date
            2016-06-24	0.165260	0.002198	0.085632	-0.078074	0.173832	0.214377	0.068445
            2016-06-27	0.165537	0.003583	0.063299	-0.048674	0.180890	0.202724	0.081748
            2016-06-28	0.135215	0.010403	0.059038	-0.034879	0.111691	0.122554	0.042489
            2016-06-29	0.068774	0.019848	0.058476	-0.049971	0.042805	0.053339	0.079592
            2016-06-30	0.039431	0.012271	0.037432	-0.027272	0.010902	0.077293	-0.050667

    :param holding_period: 持有周期(int)
    :param rollback_period: 滚动窗口，即计算每一天的因子权重时，使用了之前rollback_period下的IC时间序列来计算。
    :return: weight_df:因子权重(pd.Dataframe),
             索引（index)为datetime,columns为待合成的因子名称。
    """
    n = rollback_period
    weight_df = pd.DataFrame(index=ic_df.index, columns=ic_df.columns)
    for dt in ic_df.index:
        ic_dt = ic_df[ic_df.index <= dt].tail(n)
        if len(ic_dt) < n:
            continue
        weight = ic_dt.mean(axis=0)
        weight = np.array(weight.reshape(len(weight), ))
        weight_df.ix[dt] = weight / np.sum(weight)

    return weight_df.shift(holding_period)


# 以IC_IR为多因子组合权重
def ir_weight(ic_df,
              holding_period,
              rollback_period=120):
    """
    输入ic_df(ic值序列矩阵),指定持有期和滚动窗口，给出相应的多因子组合权重
    :param ic_df: ic值序列矩阵 （pd.Dataframe），索引（index）为datetime,columns为各因子名称。
             如：

            　　　　　　　　　　　BP	　　　CFP	　　　EP	　　ILLIQUIDITY	REVS20	　　　SRMI	　　　VOL20
            date
            2016-06-24	0.165260	0.002198	0.085632	-0.078074	0.173832	0.214377	0.068445
            2016-06-27	0.165537	0.003583	0.063299	-0.048674	0.180890	0.202724	0.081748
            2016-06-28	0.135215	0.010403	0.059038	-0.034879	0.111691	0.122554	0.042489
            2016-06-29	0.068774	0.019848	0.058476	-0.049971	0.042805	0.053339	0.079592
            2016-06-30	0.039431	0.012271	0.037432	-0.027272	0.010902	0.077293	-0.050667

    :param holding_period: 持有周期(int)
    :param rollback_period: 滚动窗口，即计算每一天的因子权重时，使用了之前rollback_period下的IC时间序列来计算。
    :return: weight_df:因子权重(pd.Dataframe),
             索引（index)为datetime,columns为待合成的因子名称。
    """
    n = rollback_period
    weight_df = pd.DataFrame(index=ic_df.index, columns=ic_df.columns)
    for dt in ic_df.index:
        ic_dt = ic_df[ic_df.index <= dt].tail(n)
        if len(ic_dt) < n:
            continue
        weight = ic_dt.mean(axis=0) / ic_dt.std(axis=0)
        weight = np.array(weight.reshape(len(weight), ))
        weight_df.ix[dt] = weight / np.sum(weight)

    return weight_df.shift(holding_period)


def combine_factors(factors_dict=None,
                    standardize_type="rank",
                    winsorization=False,
                    index_member=None,
                    weighted_method="equal_weight",
                    props=None):
    """
    # 因子间存在较强同质性时，使用施密特正交化方法对因子做正交化处理，用得到的正交化残差作为因子,默认对Admin里加载的所有因子做调整
    :param index_member:　是否是指数成分 pd.DataFrame
    :param winsorization: 是否去极值
    :param props:　当weighted_method不为equal_weight时　需传入此配置　配置内容包括
     props = {
            'dataview': None,
            "data_api": None,
            'price': None,
            'high': None,
            'low': None,
            'ret_type': 'return',
            'benchmark_price': None,
            'period': 5,
            'mask': None,
            'can_enter': None,
            'can_exit': None,
            'forward': True,
            'commission': 0.0008,
            "covariance_type": "simple",  # 还可以为"shrink"
            "rollback_period": 120
        }
    :param factors_dict: 若干因子组成的字典(dict),形式为:
                         {"factor_name_1":factor_1,"factor_name_2":factor_2}
                       　每个因子值格式为一个pd.DataFrame，索引(index)为date,column为asset
    :param standardize_type: 标准化方法，有"rank"（排序标准化）,"z_score"(z-score标准化),为空则不进行标准化操作
    :param weighted_method 组合方法，有equal_weight,ic_weight, ir_weight, max_IR.若不为equal_weight，则还需配置props参数．
    :return: new_factor 合成后所得的新因子。
    """

    def generate_props():
        props = {
            'dataview': None,
            "data_api": None,
            'price': None,
            'high': None,
            'low': None,
            'ret_type': 'return',
            'benchmark_price': None,
            'period': 5,
            'mask': None,
            'can_enter': None,
            'can_exit': None,
            'forward': True,
            'commission': 0.0008,
            "covariance_type": "simple",  # 还可以为"shrink"
            "rollback_period": 120
        }
        return props

    def standarize_factors(factors):
        if isinstance(factors, pd.DataFrame):
            factors_dict = {"factor": factors}
        else:
            factors_dict = factors
        factor_name_list = factors_dict.keys()
        for factor_name in factor_name_list:
            factors_dict[factor_name] = jutil.fillinf(factors_dict[factor_name])
            factors_dict[factor_name] = process._mask_non_index_member(factors_dict[factor_name],
                                                                       index_member=index_member)
            if winsorization:
                factors_dict[factor_name] = process.winsorize(factors_dict[factor_name])
            if standardize_type == "z_score":
                factors_dict[factor_name] = process.standardize(factors_dict[factor_name])
            elif standardize_type == "rank":
                factors_dict[factor_name] = process.rank_standardize(factors_dict[factor_name])
            elif standardize_type is not None:
                raise ValueError("standardize_type 只能为'z_score'/'rank'/None")
        return factors_dict

    def _cal_weight(weighted_method="ic_weight"):
        _props = generate_props()
        if not (props is None):
            _props.update(props)
        if _props["price"] is None or \
                (_props['ret_type'] in ["upside_ret", "downside_ret"] and (
                        _props['high'] is None or _props['low'] is None)):
            factors_name = list(factors_dict.keys())
            factor_0 = factors_dict[factors_name[0]]
            pools = list(factor_0.columns)
            start = factor_0.index[0]
            end = factor_0.index[-1]
            dv = process._prepare_data(pools, start, end,
                                       dv=_props["dataview"],
                                       ds=_props["data_api"])
        if _props["price"] is None:
            _props["price"] = dv.get_ts("close_adj")
        if _props['ret_type'] in ["upside_ret", "downside_ret"]:
            if _props['high'] is None:
                _props['high'] = dv.get_ts("high_adj")
            if _props['low'] is None:
                _props['low'] = dv.get_ts("low_adj")

        ic_df = get_factors_ic_df(factors_dict=factors_dict,
                                  **_props)
        if weighted_method == 'max_IR':
            return max_IR_weight(ic_df,
                                 _props['period'],
                                 _props["rollback_period"],
                                 _props["covariance_type"])
        elif weighted_method == "ic_weight":
            return ic_weight(ic_df,
                             _props['period'],
                             _props["rollback_period"])
        elif weighted_method == "ir_weight":
            return ir_weight(ic_df,
                             _props['period'],
                             _props["rollback_period"])
        elif weighted_method == "max_IC":
            return max_IC_weight(ic_df,
                                 factors_dict,
                                 _props['period'],
                                 _props["covariance_type"])

    def sum_weighted_factors(x, y):
        return x + y

    if not factors_dict or len(list(factors_dict.keys())) < 2:
        raise ValueError("你需要给定至少２个因子")
    factors_dict = standarize_factors(factors_dict)

    if weighted_method in ["max_IR", "max_IC", "ic_weight", "ir_weight"]:
        weight = _cal_weight(weighted_method)
        weighted_factors = {}
        factor_name_list = factors_dict.keys()
        for factor_name in factor_name_list:
            w = pd.DataFrame(data=weight[factor_name], index=factors_dict[factor_name].index)
            w = pd.concat([w] * len(factors_dict[factor_name].columns), axis=1)
            w.columns = factors_dict[factor_name].columns
            weighted_factors[factor_name] = factors_dict[factor_name] * w
    elif weighted_method == "equal_weight":
        weighted_factors = factors_dict
    else:
        raise ValueError('weighted_method 只能为equal_weight, ic_weight, ir_weight, max_IR')
    new_factor = reduce(sum_weighted_factors, weighted_factors.values())
    new_factor = standarize_factors(new_factor)["factor"]
    return new_factor
